"""Stdlib codec for the private backup owner's safe, non-authorizing status projection."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

SCHEMA = "stpd/hub-backup-status-v1"
MAX_AGE_SECONDS = 26 * 3600
FIELDS = frozenset(
    {
        "schema",
        "last_attempt_at",
        "last_status",
        "last_success_at",
        "last_backup_receipt",
        "worker_image",
    }
)


def project(value: object) -> dict[str, Any]:
    """Only validated owner facts cross the mount; no errors, secrets or private paths."""
    if not isinstance(value, dict):
        raise ValueError("backup_status_schema_invalid")
    safe = {key: item for key, item in value.items() if key in FIELDS}
    if (
        safe.get("schema") != SCHEMA
        or safe.get("last_status") not in {"running", "success", "failed"}
        or not isinstance(safe.get("last_attempt_at"), str)
    ):
        raise ValueError("backup_status_schema_invalid")
    if safe["last_status"] == "success" and not FIELDS.issubset(safe):
        raise ValueError("backup_success_requires_exact_receipt")
    for key in ("last_attempt_at", "last_success_at"):
        if key in safe:
            item = safe[key]
            if (
                not isinstance(item, str)
                or len(item) > 64
                or datetime.fromisoformat(item).utcoffset() is None
            ):
                raise ValueError("backup_status_timestamp_invalid")
    for key, pattern in (
        ("last_backup_receipt", r"[a-f0-9]{64}"),
        ("worker_image", r"[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}"),
    ):
        if key in safe and (
            not isinstance(safe[key], str) or re.fullmatch(pattern, safe[key]) is None
        ):
            raise ValueError("backup_status_identity_invalid")
    if "maximum_age_seconds" in value and (
        type(value["maximum_age_seconds"]) is not int
        or value["maximum_age_seconds"] != MAX_AGE_SECONDS
    ):
        raise ValueError("backup_status_freshness_policy_invalid")
    safe["maximum_age_seconds"] = MAX_AGE_SECONDS
    return safe


def freshness(value: object, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    age = None
    state = "unknown"
    try:
        safe = project(value)
        attempted = datetime.fromisoformat(safe["last_attempt_at"])
        if "last_success_at" in safe:
            succeeded = datetime.fromisoformat(safe["last_success_at"])
            elapsed = (now - succeeded).total_seconds()
            age = elapsed if elapsed >= 0 else None
        else:
            succeeded = None
        state = (
            "ok"
            if (
                safe["last_status"] == "success"
                and age is not None
                and age <= MAX_AGE_SECONDS
                and succeeded is not None
                and attempted <= succeeded <= now
            )
            else "attention"
        )
    except (TypeError, ValueError):
        pass
    return {
        "freshness": state,
        "backup_health": "PASS" if state == "ok" else "ATTENTION_REQUIRED",
        "age_seconds": age,
        "maximum_age_seconds": MAX_AGE_SECONDS,
    }
