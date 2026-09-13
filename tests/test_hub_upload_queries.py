from __future__ import annotations

from pathlib import Path

import pytest

from stpd.hub.database import Operations
from stpd.json_boundary import BoundaryError


def test_upload_lists_bound_history_and_filter_before_pagination(tmp_path: Path) -> None:
    ops = Operations(tmp_path / "ops.sqlite")
    first = ops.create_upload("incident", "a" * 64, "b" * 64, {"large": "x" * 65536})
    ops.request_verification(first["id"])
    for attempt in range(5):
        ops.verification_failure(first["id"], "missing_bytes", now=float(attempt))
    for number in range(105):
        ops.create_upload(f"device-{number}", "a" * 64, "b" * 64, {"large": "x" * 65536})
    latest = ops.uploads()
    assert len(latest) == 100
    assert all("intent" not in row and "manifest_sha" not in row for row in latest)
    assert first["id"] not in {row["id"] for row in latest}
    incidents = ops.uploads(statuses=("transfer_failed",), limit=1)
    assert len(incidents) == 1 and incidents[0]["id"] == first["id"]
    assert ops.uploads(statuses=("transfer_failed",), offset=1) == []
    assert len(ops.uploads(offset=100)) == 6
    assert ops.uploads("incident", statuses=("awaiting_upload",)) == []
    assert ops.uploads(statuses=()) == []
    assert ops.upload_counts() == {"awaiting_upload": 105, "transfer_failed": 1}
    assert ops.upload_counts("incident") == {"transfer_failed": 1}
    assert ops.upload_counts("absent") == {}
    assert ops.upload(first["id"])["intent"] == first["intent"]
    for pagination in ({"limit": 0}, {"limit": 1001}, {"offset": -1}, {"limit": True}):
        with pytest.raises(BoundaryError, match="invalid_upload_pagination"):
            ops.uploads(**pagination)
    with pytest.raises(BoundaryError, match="invalid_upload_status_filter"):
        ops.uploads(statuses=("made_up",))


def test_pending_upload_selects_one_due_candidate_without_transport_intent(tmp_path: Path) -> None:
    ops = Operations(tmp_path / "ops.sqlite")
    delayed = ops.create_upload("a", "a" * 64, "b" * 64, {"raw": "retained"})
    ready = ops.create_upload("b", "a" * 64, "b" * 64, {"raw": "retained"})
    ops.request_verification(delayed["id"])
    ops.verification_failure(delayed["id"], "not_ready", now=100)
    assert ops.pending_upload(101) is None
    ops.request_verification(ready["id"])
    candidate = ops.pending_upload(101)
    assert candidate and candidate["id"] == ready["id"] and "intent" not in candidate
    ops.finish_upload(
        ready["id"],
        {"status": "verified", "content_id": "a" * 64, "manifest_sha256": "b" * 64},
    )
    candidate = ops.pending_upload(102)
    assert candidate and candidate["id"] == delayed["id"]
    with pytest.raises(BoundaryError, match="invalid_verification_time"):
        ops.pending_upload(float("nan"))


def test_incident_projection_exposes_recovery_state(tmp_path: Path) -> None:
    from stpd.hub.application import HubApplication

    ops = Operations(tmp_path / "ops.sqlite")
    row = ops.create_upload("device", "a" * 64, "b" * 64, {"secret": "private-intent"})
    ops.request_verification(row["id"])
    ops.verification_failure(row["id"], "transport_or_storage_unavailable", now=100)
    status = HubApplication.upload_status(ops.upload(row["id"]))
    assert status["verify_attempts"] == 1 and status["retry_at"] == 102
    assert status["last_error"] == "transport_or_storage_unavailable"
    assert "intent" not in status and "device" not in status
    for attempt in range(4):
        ops.verification_failure(row["id"], "transport_or_storage_unavailable", now=110 + attempt)
    status = HubApplication.upload_status(ops.upload(row["id"]))
    assert status["status"] == "transfer_failed" and status["retry_at"] is None
    ops.retry_upload(row["id"])
    status = HubApplication.upload_status(ops.upload(row["id"]))
    assert status["last_error"] is None and status["verify_attempts"] == 0
    private = dict(ops.upload(row["id"]), last_error="https://storage.invalid/?secret=value")
    assert HubApplication.upload_status(private)["last_error"] == "operational_error_redacted"


def test_hub_server_import_does_not_require_workbench() -> None:
    import subprocess
    import sys

    program = """
import importlib.abc
import sys
class RejectWorkbench(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('stpd.workbench'):
            raise AssertionError('server must not import developer workbench')
sys.meta_path.insert(0, RejectWorkbench())
import stpd.hub.application
"""
    subprocess.run([sys.executable, "-c", program], check=True)
