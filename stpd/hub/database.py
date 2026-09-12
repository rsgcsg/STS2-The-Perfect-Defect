"""Single-Hub transactional operations, revocable identities and fenced attempts."""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from ..json_boundary import BoundaryError


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Operations:
    """One authoritative operational DB; do not delete it like a Registry cache."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO settings VALUES('paused','0');
                CREATE TABLE IF NOT EXISTS devices(
                    id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS uploads(
                    id TEXT PRIMARY KEY, device TEXT NOT NULL, content_id TEXT NOT NULL,
                    manifest_sha TEXT NOT NULL, intent TEXT NOT NULL, status TEXT NOT NULL,
                    receipt TEXT, verify_attempts INTEGER NOT NULL DEFAULT 0,
                    retry_at REAL NOT NULL DEFAULT 0, last_error TEXT, UNIQUE(device,content_id));
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
                    input_id TEXT NOT NULL, max_seconds INTEGER NOT NULL,
                    reserved_units INTEGER NOT NULL, status TEXT NOT NULL,
                    fence INTEGER NOT NULL DEFAULT 0, attempt_id TEXT, lease_hash TEXT,
                    lease_until REAL, deadline REAL, provider_ref TEXT, result TEXT);
                CREATE TABLE IF NOT EXISTS events(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                    actor TEXT NOT NULL, operation TEXT NOT NULL, subject TEXT NOT NULL,
                    detail TEXT NOT NULL);
            """)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            if db.in_transaction:
                db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _event(db: sqlite3.Connection, actor: str, op: str, subject: str, detail: Any) -> None:
        db.execute(
            "INSERT INTO events(at,actor,operation,subject,detail) VALUES(?,?,?,?,?)",
            (time.time(), actor, op, subject, json.dumps(detail, sort_keys=True)),
        )

    def register(self, device: str, token: str) -> None:
        if not device or len(device) > 128 or len(token) < 32:
            raise BoundaryError("hub", "invalid_device_credential")
        with self.transaction() as db:
            db.execute(
                "INSERT INTO devices(id,token_hash) VALUES(?,?)", (device, token_hash(token))
            )
            self._event(db, "admin", "device_registered", device, {})

    def authenticate(self, token: str) -> str:
        with self.transaction() as db:
            row = db.execute(
                "SELECT id FROM devices WHERE token_hash=? AND active=1", (token_hash(token),)
            ).fetchone()
            if row is None:
                raise BoundaryError("hub", "unauthorized")
            return str(row["id"])

    def revoke(self, device: str) -> None:
        with self.transaction() as db:
            db.execute("UPDATE devices SET active=0 WHERE id=?", (device,))
            self._event(db, "admin", "device_revoked", device, {})

    def create_upload(
        self, device: str, content_id: str, manifest_sha: str, intent: dict[str, Any]
    ) -> dict[str, Any]:
        encoded = json.dumps(intent, sort_keys=True, separators=(",", ":"))
        with self.transaction() as db:
            old = db.execute(
                "SELECT * FROM uploads WHERE device=? AND content_id=?", (device, content_id)
            ).fetchone()
            if old is not None:
                if old["manifest_sha"] != manifest_sha:
                    raise BoundaryError("hub", "content_manifest_conflict")
                if old["intent"] != encoded and old["status"] != "verified":
                    raise BoundaryError("hub", "upload_transport_changed")
                return dict(old)
            upload_id = secrets.token_hex(16)
            pending = db.execute(
                "SELECT COUNT(*) FROM uploads WHERE device=? AND status IN "
                "('awaiting_upload','verification_pending')",
                (device,),
            ).fetchone()[0]
            if pending >= 16:
                raise BoundaryError("hub", "upload_queue_limit")
            db.execute(
                "INSERT INTO uploads(id,device,content_id,manifest_sha,intent,status,receipt) "
                "VALUES(?,?,?,?,?,?,NULL)",
                (upload_id, device, content_id, manifest_sha, encoded, "awaiting_upload"),
            )
            self._event(db, device, "upload_created", upload_id, {"content_id": content_id})
            row = db.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
            return dict(row)

    def uploads(self, device: str | None = None) -> list[dict[str, Any]]:
        with self.transaction() as db:
            query = "SELECT * FROM uploads"
            rows = db.execute(
                query if device is None else query + " WHERE device=?",
                () if device is None else (device,),
            ).fetchall()
            return [dict(row) for row in rows]

    def upload(self, upload_id: str, device: str | None = None) -> dict[str, Any]:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
            if row is None or (device is not None and row["device"] != device):
                raise BoundaryError("hub", "upload_not_found")
            return dict(row)

    def request_verification(self, upload_id: str) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE uploads SET status='verification_pending' "
                "WHERE id=? AND status='awaiting_upload'",
                (upload_id,),
            )

    def verification_failure(self, upload_id: str, code: str, *, now: float) -> None:
        with self.transaction() as db:
            row = db.execute(
                "SELECT verify_attempts FROM uploads WHERE id=?", (upload_id,)
            ).fetchone()
            attempts = int(row[0]) + 1
            status = "transfer_failed" if attempts >= 5 else "verification_pending"
            db.execute(
                "UPDATE uploads SET verify_attempts=?,retry_at=?,last_error=?,status=? WHERE id=?",
                (attempts, now + min(300, 2**attempts), code, status, upload_id),
            )
            self._event(
                db,
                "receiver",
                "verification_retry",
                upload_id,
                {"attempt": attempts, "code": code, "status": status},
            )

    def finish_upload(self, upload_id: str, receipt: dict[str, Any]) -> None:
        if receipt.get("status") not in {"verified", "quarantined"}:
            raise BoundaryError("hub", "invalid_receive_disposition")
        with self.transaction() as db:
            row = db.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
            if row is None or (receipt.get("content_id"), receipt.get("manifest_sha256")) != (
                row["content_id"],
                row["manifest_sha"],
            ):
                raise BoundaryError("hub", "receipt_identity_mismatch")
            encoded = json.dumps(receipt, sort_keys=True)
            if row["receipt"] is not None and row["receipt"] != encoded:
                raise BoundaryError("hub", "receipt_conflict")
            db.execute(
                "UPDATE uploads SET status=?,receipt=? WHERE id=?",
                (receipt["status"], encoded, upload_id),
            )
            self._event(db, "verifier", "upload_receipt", upload_id, receipt)

    def enqueue(
        self,
        kind: str,
        input_id: str,
        request_key: str,
        *,
        max_seconds: int,
        reserved_units: int,
        budget_limit: int,
    ) -> str:
        if (
            kind not in {"feature", "training"}
            or type(max_seconds) is not int
            or not 0 < max_seconds <= 86400
        ):
            raise BoundaryError("hub", "invalid_job")
        if len(input_id) != 64 or any(c not in "0123456789abcdef" for c in input_id):
            raise BoundaryError("hub", "invalid_job_input")
        if (
            not request_key
            or type(reserved_units) is not int
            or type(budget_limit) is not int
            or reserved_units <= 0
            or budget_limit <= 0
        ):
            raise BoundaryError("hub", "invalid_budget")
        with self.transaction() as db:
            old = db.execute("SELECT * FROM jobs WHERE request_key=?", (request_key,)).fetchone()
            if old is not None:
                if (old["kind"], old["input_id"], old["max_seconds"], old["reserved_units"]) != (
                    kind,
                    input_id,
                    max_seconds,
                    reserved_units,
                ):
                    raise BoundaryError("hub", "job_request_conflict")
                return str(old["id"])
            # Reservations remain consumed after completion until an explicit new campaign.
            total = int(
                db.execute("SELECT COALESCE(SUM(reserved_units),0) FROM jobs").fetchone()[0]
            )
            if total + reserved_units > budget_limit:
                raise BoundaryError("hub", "budget_exhausted")
            job_id = secrets.token_hex(16)
            db.execute(
                "INSERT INTO jobs(id,request_key,kind,input_id,max_seconds,reserved_units,"
                "status) VALUES(?,?,?,?,?,?,'queued')",
                (job_id, request_key, kind, input_id, max_seconds, reserved_units),
            )
            self._event(db, "admin", "job_enqueued", job_id, {"input_id": input_id})
            return job_id

    def jobs(self) -> list[dict[str, Any]]:
        with self.transaction() as db:
            return [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY rowid")]

    def claim(self, owner: str, *, now: float, lease_seconds: int = 120) -> dict[str, Any] | None:
        if type(lease_seconds) is not int or not 0 < lease_seconds <= 600 or not math.isfinite(now):
            raise BoundaryError("hub", "invalid_lease")
        with self.transaction() as db:
            if db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0] == "1":
                return None
            active = db.execute(
                "SELECT 1 FROM jobs WHERE status IN "
                "('running','submission_unknown','uncertain','cancelling')"
            ).fetchone()
            if active:
                return None
            row = db.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            token = secrets.token_urlsafe(32)
            attempt = secrets.token_hex(16)
            deadline = now + int(row["max_seconds"])
            db.execute(
                "UPDATE jobs SET status='running',fence=fence+1,attempt_id=?,lease_hash=?,"
                "lease_until=?,deadline=?,provider_ref=NULL WHERE id=?",
                (
                    attempt,
                    token_hash(token),
                    min(now + lease_seconds, deadline),
                    deadline,
                    row["id"],
                ),
            )
            self._event(db, owner, "job_claimed", row["id"], {"attempt_id": attempt})
            claimed = dict(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())
            claimed.pop("lease_hash")
            return {**claimed, "lease_token": token}

    @staticmethod
    def _live(db: sqlite3.Connection, job: str, token: str, now: float) -> sqlite3.Row:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
        if (
            not math.isfinite(now)
            or row is None
            or row["status"] != "running"
            or row["lease_until"] <= now
            or not (secrets.compare_digest(row["lease_hash"] or "", token_hash(token)))
        ):
            raise BoundaryError("hub", "stale_attempt")
        return cast(sqlite3.Row, row)

    def heartbeat(self, job: str, token: str, *, now: float, lease_seconds: int = 120) -> None:
        if type(lease_seconds) is not int or not 0 < lease_seconds <= 600 or not math.isfinite(now):
            raise BoundaryError("hub", "invalid_lease")
        with self.transaction() as db:
            row = self._live(db, job, token, now)
            db.execute(
                "UPDATE jobs SET lease_until=? WHERE id=?",
                (min(now + lease_seconds, row["deadline"]), job),
            )

    def submitted(self, job: str, token: str, reference: str, *, now: float) -> None:
        if not reference or len(reference) > 512:
            raise BoundaryError("hub", "invalid_provider_reference")
        with self.transaction() as db:
            row = self._live(db, job, token, now)
            if row["provider_ref"] not in {None, reference}:
                raise BoundaryError("hub", "provider_reference_conflict")
            db.execute("UPDATE jobs SET provider_ref=? WHERE id=?", (reference, job))

    def submission_unknown(self, job: str, token: str, *, now: float) -> None:
        with self.transaction() as db:
            self._live(db, job, token, now)
            db.execute("UPDATE jobs SET status='submission_unknown' WHERE id=?", (job,))
            self._event(db, "scheduler", "submission_unknown", job, {})

    def expire(self, *, now: float) -> int:
        with self.transaction() as db:
            result = db.execute(
                "UPDATE jobs SET status='uncertain' WHERE status='running' AND lease_until<=?",
                (now,),
            )
            return result.rowcount

    def complete(self, job: str, token: str, result: dict[str, Any], *, now: float) -> None:
        with self.transaction() as db:
            self._live(db, job, token, now)
            db.execute(
                "UPDATE jobs SET status='completed',result=? WHERE id=?",
                (json.dumps(result, sort_keys=True), job),
            )
            self._event(db, "scheduler", "job_completed", job, result)

    def cancel(self, job: str) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT status FROM jobs WHERE id=?", (job,)).fetchone()
            if row is None:
                raise BoundaryError("hub", "job_not_found")
            status = "cancelled" if row[0] == "queued" else "cancelling"
            if row[0] in {"completed", "failed", "cancelled"}:
                return
            db.execute("UPDATE jobs SET status=? WHERE id=?", (status, job))
            self._event(db, "admin", "cancel_requested", job, {})

    def reconcile_stopped(self, job: str, evidence: str, *, requeue: bool = False) -> None:
        if not evidence.strip():
            raise BoundaryError("hub", "provider_stop_evidence_required")
        with self.transaction() as db:
            row = db.execute("SELECT status FROM jobs WHERE id=?", (job,)).fetchone()
            if row is None or row[0] not in {"uncertain", "submission_unknown", "cancelling"}:
                raise BoundaryError("hub", "reconciliation_not_applicable")
            if requeue:
                raise BoundaryError("hub", "new_budgeted_job_required")
            target = "cancelled" if row[0] == "cancelling" else "failed"
            db.execute("UPDATE jobs SET status=?,lease_hash=NULL WHERE id=?", (target, job))
            self._event(db, "admin", "provider_stopped", job, {"evidence": evidence})

    def pause(self, paused: bool) -> None:
        with self.transaction() as db:
            db.execute("UPDATE settings SET value=? WHERE key='paused'", ("1" if paused else "0",))
            self._event(db, "admin", "pause_changed", "hub", {"paused": paused})

    def paused(self) -> bool:
        with self.transaction() as db:
            return bool(
                db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0] == "1"
            )

    def backup(self, destination: Path) -> None:
        if destination.exists():
            raise BoundaryError("hub", "backup_exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as source, sqlite3.connect(destination) as target:
            source.backup(target)
            target.execute("UPDATE settings SET value='1' WHERE key='paused'")
            target.commit()
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BoundaryError("hub", "backup_integrity")
