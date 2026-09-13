from __future__ import annotations

import concurrent.futures
import io
import json
from pathlib import Path

import pytest

from stpd.artifact_contracts import Manifest, Producer
from stpd.hub.application import HubApplication
from stpd.hub.database import Operations
from stpd.hub.uploads import LocalStaging, UploadService
from stpd.json_boundary import BoundaryError
from stpd.storage.local import LocalBlobStore
from stpd.storage.store import ManifestArtifactStore


def test_lease_is_exclusive_and_expiry_never_proves_stopped(tmp_path: Path) -> None:
    ops = Operations(tmp_path / "ops.sqlite")
    job = ops.enqueue(
        "training", "a" * 64, "first", max_seconds=300, reserved_units=10, budget_limit=20
    )
    ops.enqueue("training", "b" * 64, "second", max_seconds=300, reserved_units=10, budget_limit=20)
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda name: ops.claim(name, now=100), ["a", "b"]))
    claimed = [value for value in claims if value is not None]
    assert len(claimed) == 1
    attempt = claimed[0]
    assert ops.expire(now=221) == 1
    assert ops.claim("replacement", now=222) is None
    with pytest.raises(BoundaryError, match="stale_attempt"):
        ops.complete(job, attempt["lease_token"], {"result_id": "c" * 64}, now=222)
    with pytest.raises(BoundaryError, match="provider_stop_evidence_required"):
        ops.reconcile_stopped(job, "")
    ops.reconcile_stopped(job, "provider status receipt: terminal")
    assert ops.claim("replacement", now=223) is not None


def test_request_identity_budget_cancel_and_credential_revocation(tmp_path: Path) -> None:
    ops = Operations(tmp_path / "ops.sqlite")
    ops.register("collector", "x" * 32)
    assert ops.authenticate("x" * 32) == "collector"
    ops.revoke("collector")
    with pytest.raises(BoundaryError, match="unauthorized"):
        ops.authenticate("x" * 32)

    def enqueue(key: str, input_id: str = "a" * 64) -> str:
        return ops.enqueue(
            "feature", input_id, key, max_seconds=100, reserved_units=10, budget_limit=10
        )

    job = enqueue("first")
    assert enqueue("first") == job
    with pytest.raises(BoundaryError, match="job_request_conflict"):
        enqueue("first", "b" * 64)
    with pytest.raises(BoundaryError, match="budget_exhausted"):
        enqueue("second")
    attempt = ops.claim("worker", now=1)
    assert attempt
    ops.cancel(job)
    with pytest.raises(BoundaryError, match="stale_attempt"):
        ops.complete(job, attempt["lease_token"], {}, now=2)
    assert ops.claim("replacement", now=1000) is None
    ops.reconcile_stopped(job, "cancelled by provider")
    assert ops.jobs()[0]["status"] == "cancelled"


def test_backup_restores_paused_and_retains_authorizations_and_uncertainty(tmp_path: Path) -> None:
    ops = Operations(tmp_path / "ops.sqlite")
    ops.register("device", "a" * 32)
    ops.enqueue("training", "a" * 64, "first", max_seconds=300, reserved_units=1, budget_limit=1)
    claim = ops.claim("old", now=1)
    assert claim
    ops.submission_unknown(claim["id"], claim["lease_token"], now=2)
    backup = tmp_path / "snapshot.sqlite"
    ops.backup(backup)
    restored = Operations(backup)
    assert restored.paused()
    assert restored.authenticate("a" * 32) == "device"
    assert restored.jobs()[0]["status"] == "submission_unknown"
    assert restored.claim("new", now=3) is None


def test_http_device_scoped_uploads_and_shared_result_reads(tmp_path: Path) -> None:
    ops = Operations(tmp_path / "ops.sqlite")
    ops.register("one", "a" * 32)
    ops.register("two", "b" * 32)
    service = UploadService(
        ops,
        LocalStaging(tmp_path / "stage", "http://127.0.0.1:8765"),
        ManifestArtifactStore(LocalBlobStore(tmp_path / "objects")),
        Producer("test", "a" * 40, "b" * 64),
    )
    app = HubApplication(service, "c" * 32)

    def call(path: str, token: str) -> tuple[str, dict]:
        statuses = []
        output = b"".join(
            app(
                {
                    "REQUEST_METHOD": "GET",
                    "PATH_INFO": path,
                    "HTTP_AUTHORIZATION": f"Bearer {token}",
                    "wsgi.input": io.BytesIO(),
                },
                lambda status, headers: statuses.append(status),
            )
        )
        return statuses[0], json.loads(output)

    assert call("/v1/jobs", "a" * 32) == ("200 OK", {"items": []})
    private = Manifest("dataset", service.producer)
    service.store.publish(private)
    assert call("/v1/artifacts/" + private.artifact_id, "a" * 32)[0] == "401 Unauthorized"
    shared = Manifest("model", service.producer)
    service.store.publish(shared)
    assert call("/v1/artifacts/" + shared.artifact_id, "a" * 32)[0] == "200 OK"
    row = ops.create_upload("one", "a" * 64, "b" * 64, {})
    assert call("/v1/uploads/" + row["id"], "b" * 32)[0] == "409 Conflict"
    assert call("/v1/uploads", "b" * 32)[1] == {
        "items": [],
        "limit": 100,
        "offset": 0,
        "next_offset": None,
    }
    assert len(call("/v1/uploads", "a" * 32)[1]["items"]) == 1


def test_idempotent_completion_options_and_restore_unpause_guard(tmp_path: Path) -> None:
    ops = Operations(tmp_path / "ops.sqlite")
    kwargs = dict(max_seconds=30, reserved_units=1, budget_limit=2)
    job = ops.enqueue("training", "a" * 64, "resume", options={"resume": "b" * 64}, **kwargs)
    with pytest.raises(BoundaryError, match="job_request_conflict"):
        ops.enqueue("training", "a" * 64, "resume", **kwargs)
    attempt = ops.claim("worker", now=1)
    assert attempt
    ops.pause(True)
    with pytest.raises(BoundaryError, match="reconcile_external_jobs_before_unpause"):
        ops.pause(False)
    ops.complete(job, attempt["lease_token"], {"result": "c" * 64}, now=2)
    ops.complete(job, attempt["lease_token"], {"result": "c" * 64}, now=100)
    with pytest.raises(BoundaryError, match="completion_conflict"):
        ops.complete(job, attempt["lease_token"], {"result": "d" * 64}, now=3)
    ops.pause(False)


def test_failed_transfer_retry_is_explicit_and_preserves_identity(tmp_path: Path) -> None:
    ops = Operations(tmp_path / "ops.sqlite")
    upload = ops.create_upload("device", "a" * 64, "b" * 64, {"archive_sha256": "c" * 64})
    ops.request_verification(upload["id"])
    for attempt in range(5):
        ops.verification_failure(upload["id"], "unavailable", now=float(attempt))
    assert ops.upload(upload["id"])["status"] == "transfer_failed"
    ops.retry_upload(upload["id"])
    row = ops.upload(upload["id"])
    assert row["status"] == "awaiting_upload" and row["verify_attempts"] == 0
    assert row["intent"] == upload["intent"]
    with pytest.raises(BoundaryError, match="upload_transport_changed"):
        ops.create_upload("device", "a" * 64, "b" * 64, {"archive_sha256": "d" * 64})


def test_backup_returns_closed_standalone_snapshot(tmp_path: Path) -> None:
    import shutil
    import sqlite3
    from contextlib import closing

    ops = Operations(tmp_path / "live.sqlite")
    ops.register("collector", "x" * 32)
    destination = tmp_path / "snapshot.sqlite"
    ops.backup(destination)
    assert not Path(str(destination) + "-wal").exists()
    assert not Path(str(destination) + "-shm").exists()
    transferred = tmp_path / "downloaded.sqlite"
    shutil.copyfile(destination, transferred)
    with closing(sqlite3.connect(transferred.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0] == "1"
        assert db.execute("SELECT id FROM devices").fetchone()[0] == "collector"
