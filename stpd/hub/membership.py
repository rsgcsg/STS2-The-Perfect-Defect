"""Hub-owned invited membership and device control in the Operations transaction.

Cloudflare establishes a signed identity. Only this durable, explicitly bootstrapped
membership grants project access; browser mutations never accept personal tokens.
"""

from __future__ import annotations

import re
import secrets
import sqlite3
import time
from dataclasses import replace
from typing import Any, cast

from ..json_boundary import BoundaryError
from .console_auth import ConsolePrincipal, validate_legacy_principals, verified_identity
from .console_index import timestamp
from .database import Operations


def member_email(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 254
        or re.fullmatch(r"[^\s@]+@[^\s@]+", value) is None
    ):
        raise BoundaryError("membership", "invalid_member_email")
    return value.casefold()


def settings(value: Any, *, invite: bool) -> dict[str, Any]:
    allowed = {"role", "enroll_devices", "device_quota"} | ({"email"} if invite else {"status"})
    if not isinstance(value, dict) or not value or value.keys() - allowed:
        raise BoundaryError("membership", "invalid_member_request")
    result = dict(value)
    if invite:
        result["email"] = member_email(result.get("email"))
        result.setdefault("role", "member")
        result.setdefault("enroll_devices", True)
        result.setdefault("device_quota", 3)
    if (
        ("role" in result and result["role"] not in ("member", "admin"))
        or ("status" in result and result["status"] not in ("active", "disabled"))
        or ("enroll_devices" in result and type(result["enroll_devices"]) is not bool)
        or (
            "device_quota" in result
            and (type(result["device_quota"]) is not int or not 0 <= result["device_quota"] <= 128)
        )
    ):
        raise BoundaryError("membership", "invalid_member_request")
    return result


class MembershipService:
    def __init__(self, operations: Operations) -> None:
        self.ops = operations

    @staticmethod
    def initialized(db: sqlite3.Connection) -> bool:
        return (
            db.execute(
                "SELECT 1 FROM settings WHERE key='membership_initialized' AND value='1'"
            ).fetchone()
            is not None
        )

    @staticmethod
    def member(db: sqlite3.Connection, identity: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM identity_members WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise BoundaryError("membership", "member_not_found")
        return cast(sqlite3.Row, row)

    @staticmethod
    def insert(
        db: sqlite3.Connection,
        value: dict[str, Any],
        issuer: str,
        *,
        profile: sqlite3.Row | None = None,
        access_subject: str | None = None,
    ) -> str:
        identity, now = secrets.token_hex(16), time.time()
        db.execute(
            "INSERT INTO identity_members(id,email,issuer,access_subject,subject,role,status,"
            "enroll_devices,device_quota,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                identity,
                value["email"],
                issuer,
                profile["access_subject"] if profile else access_subject,
                profile["subject"] if profile else None,
                value["role"],
                "active" if profile else "invited",
                int(value["enroll_devices"]),
                value["device_quota"],
                now,
                now,
            ),
        )
        return identity

    def bootstrap(
        self,
        *,
        issuer: str,
        admin_email: str,
        legacy_principals: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Explicit operator-only initialization; no role or restart can auto-bootstrap."""
        if re.fullmatch(r"https://[a-z0-9-]+\.cloudflareaccess\.com", issuer) is None:
            raise BoundaryError("membership", "invalid_access_issuer")
        administrator = member_email(admin_email)
        legacy = validate_legacy_principals(legacy_principals) if legacy_principals else []
        entries = {entry["email"].casefold(): entry for entry in legacy}
        entries.setdefault(administrator, {"email": administrator, "devices": []})
        with self.ops.transaction() as db:
            if self.initialized(db) or db.execute("SELECT 1 FROM identity_members").fetchone():
                raise BoundaryError("membership", "membership_already_initialized")
            for email, entry in entries.items():
                rows = db.execute(
                    "SELECT * FROM identity_users WHERE issuer=? AND lower(email)=?",
                    (issuer, email),
                ).fetchall()
                required = entry.get("subject")
                if len(rows) > 1 or (rows and required and rows[0]["access_subject"] != required):
                    raise BoundaryError("membership", "legacy_identity_ambiguous")
                profile = rows[0] if rows else None
                if (
                    profile
                    and verified_identity(issuer, profile["access_subject"], email).subject
                    != profile["subject"]
                ):
                    raise BoundaryError("membership", "legacy_identity_inconsistent")
                value = {
                    "email": email,
                    "role": "admin" if email == administrator else "member",
                    "enroll_devices": entry.get("enroll_devices", True),
                    "device_quota": 3,
                }
                identity = self.insert(db, value, issuer, profile=profile, access_subject=required)
                for device in entry["devices"]:
                    db.execute("INSERT INTO identity_claim_scopes VALUES(?,?)", (identity, device))
            db.execute("INSERT INTO settings VALUES('membership_initialized','1')")
            self.ops._event(
                db, "operator", "membership_bootstrapped", "project", {"members": len(entries)}
            )
        return {"initialized": True, "members": len(entries)}

    def authorize(
        self, db: sqlite3.Connection, principal: ConsolePrincipal, *, activate: bool = False
    ) -> ConsolePrincipal:
        if not self.initialized(db):
            raise BoundaryError("membership", "membership_not_initialized")
        row = db.execute(
            "SELECT * FROM identity_members WHERE subject=?", (principal.subject,)
        ).fetchone()
        if row is None and activate:
            row = db.execute(
                "SELECT * FROM identity_members WHERE email=? AND issuer=? AND subject IS NULL "
                "AND status='invited'",
                (member_email(principal.email), principal.issuer),
            ).fetchone()
            if row and (
                row["access_subject"] is None or row["access_subject"] == principal.access_subject
            ):
                db.execute(
                    "INSERT INTO identity_users(subject,issuer,access_subject,email) "
                    "VALUES(?,?,?,?) "
                    "ON CONFLICT(subject) DO UPDATE SET email=excluded.email",
                    (
                        principal.subject,
                        principal.issuer,
                        principal.access_subject,
                        principal.email,
                    ),
                )
                db.execute(
                    "UPDATE identity_members SET subject=?,access_subject=?,status='active',"
                    "updated_at=? WHERE id=?",
                    (principal.subject, principal.access_subject, time.time(), row["id"]),
                )
                self.ops._event(db, principal.subject, "membership_activated", row["id"], {})
                row = self.member(db, row["id"])
            else:
                row = None
        if (
            row is None
            or row["status"] != "active"
            or row["issuer"] != principal.issuer
            or row["access_subject"] != principal.access_subject
            or row["subject"] != principal.subject
        ):
            raise BoundaryError("membership", "membership_not_authorized")
        owned = tuple(
            r[0]
            for r in db.execute(
                "SELECT id FROM devices WHERE owner_subject=? ORDER BY id", (principal.subject,)
            )
        )
        claims = tuple(
            r[0]
            for r in db.execute(
                "SELECT device_id FROM identity_claim_scopes WHERE member_id=? ORDER BY device_id",
                (row["id"],),
            )
        )
        return replace(
            principal,
            role=row["role"],
            member_id=row["id"],
            membership_status=row["status"],
            devices=tuple(sorted(set(owned) | set(claims))),
            owned_devices=owned,
            claim_devices=claims,
            enroll_devices=bool(row["enroll_devices"]),
            device_quota=row["device_quota"],
        )

    def admin(self, db: sqlite3.Connection, principal: ConsolePrincipal) -> ConsolePrincipal:
        # Personal tokens deliberately carry no Access session binding.
        current = self.authorize(db, principal)
        if (
            current.role != "admin"
            or not current.session_binding
            or current.expires_at <= time.time()
        ):
            raise BoundaryError("membership", "admin_browser_required")
        return current

    @staticmethod
    def public(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        counts = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(active),0) FROM devices WHERE owner_subject=?",
            (row["subject"],),
        ).fetchone()
        return {
            "member_id": row["id"],
            "email": row["email"],
            "role": row["role"],
            "status": row["status"],
            "subject": row["subject"],
            "enroll_devices": bool(row["enroll_devices"]),
            "device_quota": row["device_quota"],
            "owned_device_count": counts[0],
            "active_device_count": counts[1],
            "created_at": timestamp(row["created_at"]),
            "updated_at": timestamp(row["updated_at"]),
        }

    def list(
        self, principal: ConsolePrincipal, *, limit: int = 25, offset: int = 0
    ) -> dict[str, Any]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(offset) is not int
            or not 0 <= offset <= 100000
        ):
            raise BoundaryError("membership", "invalid_member_pagination")
        with self.ops.transaction() as db:
            self.admin(db, principal)
            rows = db.execute(
                "SELECT * FROM identity_members ORDER BY created_at,id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return {
                "items": [self.public(db, row) for row in rows],
                "total": db.execute("SELECT COUNT(*) FROM identity_members").fetchone()[0],
                "limit": limit,
                "offset": offset,
                "observed_at": timestamp(),
            }

    def invite(self, principal: ConsolePrincipal, value: Any) -> dict[str, Any]:
        value = settings(value, invite=True)
        with self.ops.transaction() as db:
            current = self.admin(db, principal)
            if db.execute(
                "SELECT 1 FROM identity_members WHERE email=?", (value["email"],)
            ).fetchone():
                raise BoundaryError("membership", "member_already_exists")
            if db.execute("SELECT COUNT(*) FROM identity_members").fetchone()[0] >= 1000:
                raise BoundaryError("membership", "member_capacity")
            identity = self.insert(db, value, current.issuer)
            self.ops._event(
                db, current.subject, "member_invited", identity, {"role": value["role"]}
            )
            return self.public(db, self.member(db, identity))

    def update(self, principal: ConsolePrincipal, identity: str, value: Any) -> dict[str, Any]:
        changes = settings(value, invite=False)
        with self.ops.transaction() as db:
            current = self.admin(db, principal)
            member = self.member(db, identity)
            role, status = (
                changes.get("role", member["role"]),
                changes.get("status", member["status"]),
            )
            if status == "active" and member["subject"] is None:
                status = "invited"
            removing_admin = (
                member["role"] == "admin"
                and member["status"] == "active"
                and (role != "admin" or status != "active")
            )
            if (
                removing_admin
                and db.execute(
                    "SELECT COUNT(*) FROM identity_members WHERE role='admin' AND status='active'"
                ).fetchone()[0]
                <= 1
            ):
                raise BoundaryError("membership", "last_admin_required")
            db.execute(
                "UPDATE identity_members SET role=?,status=?,enroll_devices=?,device_quota=?,"
                "updated_at=? WHERE id=?",
                (
                    role,
                    status,
                    int(changes.get("enroll_devices", member["enroll_devices"])),
                    changes.get("device_quota", member["device_quota"]),
                    time.time(),
                    identity,
                ),
            )
            if status == "disabled" and member["subject"]:
                self.clear_sessions(db, member["subject"])
                db.execute(
                    "UPDATE devices SET active=0 WHERE owner_subject=?", (member["subject"],)
                )
            self.ops._event(
                db,
                current.subject,
                "member_updated",
                identity,
                {"fields": sorted(changes), "role": role, "status": status},
            )
            return self.public(db, self.member(db, identity))

    @staticmethod
    def clear_sessions(db: sqlite3.Connection, subject: str) -> None:
        db.execute("DELETE FROM identity_sessions WHERE subject=?", (subject,))
        db.execute(
            "UPDATE identity_flows SET status='denied' WHERE subject=? AND status='approved'",
            (subject,),
        )

    def revoke_sessions(self, principal: ConsolePrincipal, identity: str) -> dict[str, str]:
        with self.ops.transaction() as db:
            current = self.admin(db, principal)
            row = self.member(db, identity)
            if row["subject"]:
                self.clear_sessions(db, row["subject"])
            self.ops._event(db, current.subject, "member_sessions_revoked", identity, {})
        return {"status": "revoked"}

    def revoke_device(self, principal: ConsolePrincipal, device: str) -> dict[str, str]:
        with self.ops.transaction() as db:
            current = self.authorize(db, principal)
            if not current.session_binding or current.expires_at <= time.time():
                raise BoundaryError("membership", "browser_identity_required")
            row = db.execute("SELECT * FROM devices WHERE id=?", (device,)).fetchone()
            if row is None or (current.role != "admin" and row["owner_subject"] != current.subject):
                raise BoundaryError("membership", "identity_device_not_authorized")
            db.execute("UPDATE devices SET active=0 WHERE id=?", (device,))
            self.ops._event(db, current.subject, "device_revoked", device, {})
        return {"device_id": device, "status": "revoked"}
