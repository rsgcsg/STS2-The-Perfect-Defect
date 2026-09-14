"""Human-approved device enrollment and personal read sessions in the owning Hub DB.

Browser identity authorizes a bounded connection, never a recording campaign. Device
credentials and personal read tokens remain distinct after enrollment and logout.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from dataclasses import replace
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit

from ..json_boundary import BoundaryError
from .console_auth import AccessVerifier, ConsolePrincipal, verified_identity
from .console_index import timestamp
from .database import Operations, token_hash
from .membership import MembershipService

PERSONAL_PREFIX = "stpd_personal_"
FLOW_SECONDS = 600
SESSION_SECONDS = 86400


def fields(value: Any, required: set[str], optional: set[str] | None = None) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or not required <= value.keys()
        or value.keys() - required - (optional or set())
    ):
        raise BoundaryError("identity", "invalid_identity_request")
    return value


def text(value: Any, maximum: int = 128) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or value.strip() != value
        or any(ord(c) < 32 for c in value)
    ):
        raise BoundaryError("identity", "invalid_identity_request")
    return value


def client_hash(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", value) is None:
        raise BoundaryError("identity", "invalid_identity_request")
    return token_hash(value)


class IdentityService:
    def __init__(
        self,
        operations: Operations,
        access: AccessVerifier | None,
        key: bytes,
        public_origin: str = "",
    ) -> None:
        self.ops, self.access, self.key = operations, access, key
        self.membership = MembershipService(operations)
        self.key_id = self.mac("key-id")
        self.origin = ""
        if public_origin:
            parsed = urlsplit(public_origin)
            if (
                parsed.scheme == "https"
                and parsed.hostname
                and not parsed.username
                and not parsed.password
                and not parsed.query
                and not parsed.fragment
                and parsed.path in {"", "/"}
            ):
                self.origin = public_origin.rstrip("/")

    def mac(self, *parts: str) -> str:
        message = json.dumps(parts, separators=(",", ":")).encode()
        return hmac.new(self.key, message, hashlib.sha256).hexdigest()

    def required_access(self) -> AccessVerifier:
        if self.access is None:
            raise BoundaryError("identity", "browser_access_not_configured")
        return self.access

    def rate(self, source: str, operation: str, limit: int) -> None:
        """Bound public requests by the actual socket source, never forwarded headers."""
        bucket = int(time.time() // 60)
        identity = self.mac("source", operation, source)
        with self.ops.transaction() as db:
            db.execute("DELETE FROM identity_rates WHERE bucket<?", (bucket,))
            row = db.execute(
                "SELECT count FROM identity_rates WHERE source=? AND bucket=?", (identity, bucket)
            ).fetchone()
            if row and row[0] >= limit:
                raise BoundaryError("identity", "identity_rate_limited")
            if (
                row is None
                and db.execute("SELECT COUNT(*) FROM identity_rates").fetchone()[0] >= 2048
            ):
                raise BoundaryError("identity", "identity_rate_limited")
            db.execute(
                "INSERT INTO identity_rates VALUES(?,?,1) "
                "ON CONFLICT(source,bucket) DO UPDATE SET count=count+1",
                (identity, bucket),
            )

    def principal(self, principal: ConsolePrincipal) -> ConsolePrincipal:
        with self.ops.transaction() as db:
            return self.membership.authorize(
                db, principal, activate=bool(principal.session_binding)
            )

    def devices(self, principal: ConsolePrincipal) -> list[dict[str, Any]]:
        result = []
        with self.ops.transaction() as db:
            principal = self.membership.authorize(db, principal)
            identities = (
                [row[0] for row in db.execute("SELECT id FROM devices ORDER BY id")]
                if principal.project_shared
                else principal.devices
            )
            for identity in identities:
                row = db.execute("SELECT * FROM devices WHERE id=?", (identity,)).fetchone()
                result.append(
                    {
                        "device_id": identity,
                        "name": row["name"] or identity if row else identity,
                        "active": bool(row["active"]) if row else None,
                        "last_seen": timestamp(row["last_seen"])
                        if row and row["last_seen"]
                        else None,
                        "presence": "not_observed",
                        "can_revoke": bool(
                            row
                            and row["active"]
                            and (
                                principal.role == "admin"
                                or row["owner_subject"] == principal.subject
                            )
                        ),
                        "ownership": (
                            "owned_by_you"
                            if row["owner_subject"] == principal.subject
                            else "shared"
                            if row["owner_subject"]
                            else "unclaimed"
                        )
                        if row
                        else "not_registered",
                    }
                )
        return result

    def me(self, principal: ConsolePrincipal, *, browser: bool = False) -> dict[str, Any]:
        principal = self.principal(principal)
        result = {
            "principal": principal.public(),
            "devices": self.devices(principal),
            "observed_at": timestamp(),
        }
        if browser:
            deadline = int(min(time.time() + FLOW_SECONDS, principal.expires_at))
            result["csrf_token"] = f"{deadline}." + self.mac(
                "csrf", principal.subject, principal.session_binding, str(deadline)
            )
        return result

    def check_browser_write(self, principal: ConsolePrincipal, origin: str, csrf: Any) -> None:
        if not principal.session_binding or principal.expires_at <= time.time():
            raise BoundaryError("identity", "browser_identity_required")
        if not self.origin or origin != self.origin:
            raise BoundaryError("identity", "identity_origin_rejected")
        try:
            deadline, signature = text(csrf, 100).split(".")
            expiry = int(deadline)
            if (
                expiry <= time.time()
                or expiry > principal.expires_at
                or not secrets.compare_digest(
                    signature,
                    self.mac("csrf", principal.subject, principal.session_binding, deadline),
                )
            ):
                raise ValueError
        except (ValueError, TypeError):
            raise BoundaryError("identity", "identity_csrf_rejected") from None

    def device(self, token: str, *, heartbeat: bool = False) -> dict[str, Any]:
        if token.startswith(PERSONAL_PREFIX):
            raise BoundaryError("identity", "unauthorized")
        with self.ops.transaction() as db:
            row = self.ops.authenticated_device(db, token)
            seen = time.time() if heartbeat else row["last_seen"]
            if heartbeat:
                db.execute("UPDATE devices SET last_seen=? WHERE id=?", (seen, row["id"]))
            return {
                "device_id": row["id"],
                "name": row["name"] or row["id"],
                "active": True,
                "last_seen": timestamp(seen) if seen else None,
                "presence": "not_observed",
            }

    def create(self, value: Any) -> dict[str, Any]:
        self.required_access()
        body = fields(value, {"client_secret", "device_name"}, {"device_id", "device_token"})
        secret_hash, name = client_hash(body["client_secret"]), text(body["device_name"], 100)
        identity, proof = body.get("device_id"), body.get("device_token")
        if (identity is None) != (proof is None):
            raise BoundaryError("identity", "existing_device_proof_required")
        if identity is not None:
            identity, proof = text(identity), text(proof, 4096)
            if self.device(proof)["device_id"] != identity:
                raise BoundaryError("identity", "unauthorized")
        now = time.time()
        flow = secrets.token_hex(16)
        code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
        with self.ops.transaction() as db:
            db.execute("DELETE FROM identity_flows WHERE expires_at<=?", (now,))
            db.execute("DELETE FROM identity_sessions WHERE expires_at<=?", (now,))
            if db.execute("SELECT COUNT(*) FROM identity_flows").fetchone()[0] >= 1000:
                raise BoundaryError("identity", "identity_flow_capacity")
            db.execute(
                "INSERT INTO identity_flows(id,client_hash,device_name,device_id,device_proof_hash,"
                "user_code,created_at,expires_at,status,key_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    flow,
                    secret_hash,
                    name,
                    identity,
                    token_hash(proof) if proof else None,
                    code,
                    now,
                    now + FLOW_SECONDS,
                    "pending",
                    self.key_id,
                ),
            )
        return {
            "flow_id": flow,
            "approval_path": "/app/?view=connect&flow=" + flow,
            "expires_at": timestamp(now + FLOW_SECONDS),
            "user_code": code,
            "poll_interval_seconds": 3,
        }

    @staticmethod
    def flow(db: sqlite3.Connection, identity: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM identity_flows WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise BoundaryError("identity", "identity_flow_not_found")
        return cast(sqlite3.Row, row)

    def flow_view(self, identity: str, principal: ConsolePrincipal) -> dict[str, Any]:
        with self.ops.transaction() as db:
            principal = self.membership.authorize(db, principal)
            row = self.flow(db, identity)
            state = "expired" if row["expires_at"] <= time.time() else row["status"]
            return {
                "flow_id": identity,
                "device_name": row["device_name"],
                "device_id": row["device_id"],
                "user_code": row["user_code"],
                "purpose": "connect_existing_device"
                if row["device_proof_hash"]
                else "enroll_device",
                "expires_at": timestamp(row["expires_at"]),
                "status": state,
                "approval_allowed": state == "pending"
                and row["key_id"] == self.key_id
                and self.eligible(db, row, principal),
                "recording_consent": "not_granted_by_connection",
            }

    @staticmethod
    def eligible(db: sqlite3.Connection, row: sqlite3.Row, principal: ConsolePrincipal) -> bool:
        active_owned = db.execute(
            "SELECT COUNT(*) FROM devices WHERE owner_subject=? AND active=1", (principal.subject,)
        ).fetchone()[0]
        if row["device_proof_hash"] is None:
            return principal.enroll_devices and active_owned < principal.device_quota
        device = db.execute("SELECT * FROM devices WHERE id=?", (row["device_id"],)).fetchone()
        return bool(
            device
            and Operations.device_authorized(db, device["id"])
            and device["token_hash"] == row["device_proof_hash"]
            and device["owner_subject"] in {None, principal.subject}
            and (
                device["owner_subject"] == principal.subject
                or (
                    device["id"] in principal.claim_devices
                    and active_owned < principal.device_quota
                )
            )
        )

    def token(self, purpose: str, row: sqlite3.Row) -> str:
        return "stpd_" + purpose + "_" + self.mac(purpose, row["id"], row["client_hash"])

    def decide(self, identity: str, value: Any, principal: ConsolePrincipal, *, deny: bool) -> dict:
        body = fields(value, {"csrf_token", "user_code"})
        code = text(body["user_code"], 8)
        now = time.time()
        with self.ops.transaction() as db:
            principal = self.membership.authorize(db, principal)
            row = self.flow(db, identity)
            if (
                row["status"] != "pending"
                or row["expires_at"] <= now
                or row["key_id"] != self.key_id
            ):
                raise BoundaryError("identity", "identity_flow_not_pending")
            if not secrets.compare_digest(row["user_code"], code):
                raise BoundaryError("identity", "identity_code_rejected")
            if deny:
                db.execute("UPDATE identity_flows SET status='denied' WHERE id=?", (identity,))
                self.ops._event(db, principal.subject, "identity_connection_denied", identity, {})
                return {"status": "denied"}
            if not self.eligible(db, row, principal):
                raise BoundaryError("identity", "identity_device_not_authorized")
            expiry = min(now + SESSION_SECONDS, principal.expires_at)
            if expiry <= now:
                raise BoundaryError("identity", "unauthorized")
            db.execute("DELETE FROM identity_sessions WHERE expires_at<=?", (now,))
            if (
                db.execute(
                    "SELECT COUNT(*) FROM identity_sessions WHERE subject=?", (principal.subject,)
                ).fetchone()[0]
                >= 32
            ):
                raise BoundaryError("identity", "identity_session_capacity")
            device_id = row["device_id"]
            new_device = device_id is None
            if new_device:
                device_id = "device-" + secrets.token_hex(16)
                db.execute(
                    "INSERT INTO devices(id,token_hash,name,owner_subject) VALUES(?,?,?,?)",
                    (
                        device_id,
                        token_hash(self.token("device", row)),
                        row["device_name"],
                        principal.subject,
                    ),
                )
                self.ops._event(
                    db,
                    principal.subject,
                    "device_registered",
                    device_id,
                    {"via": "human_approved_connection"},
                )
            else:
                db.execute(
                    "UPDATE devices SET owner_subject=?,name=COALESCE(name,?) WHERE id=?",
                    (principal.subject, row["device_name"], device_id),
                )
            session_hash = token_hash(self.token("personal", row))
            db.execute(
                "INSERT INTO identity_sessions VALUES(?,?,?,?)",
                (session_hash, principal.subject, expiry, now),
            )
            db.execute(
                "UPDATE identity_flows SET status='approved',subject=?,session_hash=?,"
                "session_expires_at=?,device_id=?,new_device=? WHERE id=?",
                (principal.subject, session_hash, expiry, device_id, int(new_device), identity),
            )
            self.ops._event(
                db,
                principal.subject,
                "identity_connection_approved",
                identity,
                {"device_id": device_id, "new_device": new_device},
            )
        return {"status": "approved"}

    def personal(self, token: str) -> ConsolePrincipal:
        self.required_access()
        if re.fullmatch(PERSONAL_PREFIX + r"[a-f0-9]{64}", token) is None:
            raise BoundaryError("identity", "unauthorized")
        with self.ops.transaction() as db:
            row = db.execute(
                "SELECT u.*,s.expires_at FROM identity_sessions s JOIN identity_users u "
                "ON u.subject=s.subject WHERE s.token_hash=? AND s.expires_at>?",
                (token_hash(token), time.time()),
            ).fetchone()
            if row is None:
                raise BoundaryError("identity", "unauthorized")
            principal = verified_identity(row["issuer"], row["access_subject"], row["email"])
            return self.membership.authorize(db, replace(principal, expires_at=row["expires_at"]))

    def poll(self, identity: str, value: Any, *, acknowledge: bool = False) -> dict[str, Any]:
        body = fields(value, {"client_secret"})
        proof = client_hash(body["client_secret"])
        with self.ops.transaction() as db:
            row = db.execute("SELECT * FROM identity_flows WHERE id=?", (identity,)).fetchone()
            if row is None:
                return {"status": "expired"}
            if not secrets.compare_digest(row["client_hash"], proof):
                raise BoundaryError("identity", "unauthorized")
            if row["expires_at"] <= time.time():
                return {"status": "expired"}
            if row["status"] == "acknowledged" and acknowledge:
                return {"status": "acknowledged"}
            if row["status"] in {"denied", "acknowledged"}:
                return {"status": "denied"}
            if row["key_id"] != self.key_id:
                raise BoundaryError("identity", "identity_flow_key_changed")
            if row["status"] != "approved":
                if acknowledge:
                    raise BoundaryError("identity", "identity_flow_not_approved")
                return {"status": "pending"}
            if acknowledge:
                db.execute(
                    "UPDATE identity_flows SET status='acknowledged' WHERE id=?", (identity,)
                )
                return {"status": "acknowledged"}
            token = self.token("personal", row)
            device = {"device_id": row["device_id"], "name": row["device_name"]}
            if row["new_device"]:
                secret = self.token("device", row)
                current = db.execute(
                    "SELECT active,token_hash FROM devices WHERE id=?", (row["device_id"],)
                ).fetchone()
                if (
                    not current
                    or not current["active"]
                    or current["token_hash"] != token_hash(secret)
                ):
                    raise BoundaryError("identity", "identity_device_not_authorized")
                device["token"] = secret
        # Membership may have changed since approval. Recheck before returning any credential.
        principal = self.personal(token)
        return {
            "status": "approved",
            "session_token": token,
            "expires_at": timestamp(row["session_expires_at"]),
            "principal": principal.public(),
            "device": device,
        }

    def logout(self, token: str) -> dict[str, str]:
        if re.fullmatch(PERSONAL_PREFIX + r"[a-f0-9]{64}", token) is None:
            raise BoundaryError("identity", "unauthorized")
        with self.ops.transaction() as db:
            row = db.execute(
                "SELECT subject FROM identity_sessions WHERE token_hash=?", (token_hash(token),)
            ).fetchone()
            db.execute("DELETE FROM identity_sessions WHERE token_hash=?", (token_hash(token),))
            if row:
                self.ops._event(db, row["subject"], "personal_session_logged_out", "self", {})
        return {"status": "logged_out"}

    def scoped_query(self, principal: ConsolePrincipal, query: str) -> tuple[ConsolePrincipal, str]:
        try:
            values = parse_qsl(query, strict_parsing=True, keep_blank_values=True, max_num_fields=4)
            devices = [value for name, value in values if name == "device"]
            if len(devices) > 1:
                raise ValueError
            if devices:
                with self.ops.transaction() as db:
                    principal = self.membership.authorize(db, principal)
                    if (
                        not principal.project_shared
                        or db.execute("SELECT 1 FROM devices WHERE id=?", (devices[0],)).fetchone()
                        is None
                    ):
                        raise ValueError
        except ValueError:
            raise BoundaryError("identity", "identity_device_not_authorized") from None
        scoped = replace(principal, data_device=devices[0]) if devices else principal
        return scoped, urlencode([(name, value) for name, value in values if name != "device"])
