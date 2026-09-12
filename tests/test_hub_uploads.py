from __future__ import annotations

import concurrent.futures
import hashlib
import io
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sts2_platform_evidence import DirectoryTransferManifest

from stpd.artifact_contracts import Producer
from stpd.hub.database import Operations
from stpd.hub.uploads import LocalStaging, UploadService
from stpd.json_boundary import BoundaryError
from stpd.storage.local import LocalBlobStore
from stpd.storage.store import ManifestArtifactStore


def fixture(tmp_path: Path) -> tuple[UploadService, dict, bytes]:
    ops = Operations(tmp_path / "ops.sqlite")
    stage = LocalStaging(tmp_path / "stage", "http://127.0.0.1:1")
    store = ManifestArtifactStore(LocalBlobStore(tmp_path / "store"))
    service = UploadService(ops, stage, store, Producer("test", "a" * 40, "b" * 64))
    directory = tmp_path / "source"
    directory.mkdir()
    (directory / "evidence.json").write_bytes(b"immutable test fixture")
    transfer = DirectoryTransferManifest.from_directory(
        directory, content_id="a" * 64, artifact_type="human-session-bundle"
    )
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        archive.add(directory / "evidence.json", arcname="evidence.json")
    data = output.getvalue()
    intent = {
        "schema": "stpd/upload-intent-v1",
        "transfer_manifest": transfer.to_dict(),
        "archive_sha256": hashlib.sha256(data).hexdigest(),
        "archive_bytes": len(data),
    }
    return service, intent, data


def test_concurrent_local_publication_same_bytes_and_collision(tmp_path: Path) -> None:
    stage = LocalStaging(tmp_path, "http://127.0.0.1:1")
    data = b"some immutable bytes" * 1000
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        results = list(
            pool.map(lambda _: stage.write("upload", io.BytesIO(data), len(data)), range(4))
        )
    assert results == [None] * 4
    assert (tmp_path / "upload").read_bytes() == data
    with pytest.raises(BoundaryError, match="staging_collision"):
        stage.write("upload", io.BytesIO(b"other"), 5)
    assert (tmp_path / "upload").read_bytes() == data
    assert list(tmp_path.iterdir()) == [tmp_path / "upload"]


def test_missing_object_does_not_starve_and_owner_findings_are_preserved(tmp_path: Path) -> None:
    service, intent, data = fixture(tmp_path)
    missing = service.intent("missing", intent)["upload_id"]
    present = service.intent("present", intent)["upload_id"]
    assert isinstance(service.staging, LocalStaging)
    service.staging.write(present, io.BytesIO(data), len(data))
    service.operations.request_verification(missing)
    service.operations.request_verification(present)
    owner_result = SimpleNamespace(
        passed=False, findings=[SimpleNamespace(code="exact_owner_failure")]
    )
    with patch("stpd.hub.uploads.verify_human_session_bundle", return_value=owner_result):
        assert service.verify_pending() == 2
    assert service.operations.upload(missing)["status"] == "verification_pending"
    assert service.operations.upload(missing)["verify_attempts"] == 1
    receipt = service.operations.upload(present)["receipt"]
    assert "exact_owner_failure" in receipt
    assert service.operations.upload(present)["status"] == "quarantined"
    assert service.verify_pending() == 0
    for _attempt in range(4):
        service.operations.verification_failure(missing, "missing", now=time.time())
    assert service.operations.upload(missing)["status"] == "transfer_failed"


def test_disk_failure_is_not_semantic_quarantine(tmp_path: Path) -> None:
    service, intent, data = fixture(tmp_path)
    upload_id = service.intent("one", intent)["upload_id"]
    assert isinstance(service.staging, LocalStaging)
    service.staging.write(upload_id, io.BytesIO(data), len(data))
    service.operations.request_verification(upload_id)
    with patch("stpd.hub.uploads.unpack", side_effect=OSError("disk full")):
        service.verify_pending()
    row = service.operations.upload(upload_id)
    assert row["status"] == "verification_pending" and row["receipt"] is None
    assert row["last_error"] == "transport_or_storage_unavailable"


@pytest.mark.parametrize("bad", [0.4, True, float("nan"), float("inf")])
def test_noninteger_budget_and_time_rejected(tmp_path: Path, bad: object) -> None:
    ops = Operations(tmp_path / "ops.sqlite")
    with pytest.raises(BoundaryError):
        ops.enqueue("training", "a" * 64, "job", max_seconds=10, reserved_units=bad, budget_limit=1)  # type: ignore[arg-type]
    with pytest.raises(BoundaryError):
        ops.enqueue("training", "a" * 64, "job", max_seconds=bad, reserved_units=1, budget_limit=1)  # type: ignore[arg-type]
    assert ops.jobs() == []
