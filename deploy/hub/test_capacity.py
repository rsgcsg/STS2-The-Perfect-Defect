"""Host stdlib gate and safe backup projection, without real Docker or remote state."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import maintenance
import preflight
import pytest
from test_support import PosixPermissionFixture

from stpd.hub.console_routes import ConsoleRoutes


@pytest.fixture(autouse=True)
def portable_permissions(monkeypatch):
    monkeypatch.setattr(maintenance, "owner_uid", lambda path: 0)
    fixture = PosixPermissionFixture()
    fixture.setUp()
    try:
        yield
    finally:
        fixture.doCleanups()


def status():
    return {
        "schema": maintenance.SCHEMA,
        "last_status": "success",
        "last_attempt_at": datetime.now(UTC).isoformat(),
        "last_success_at": datetime.now(UTC).isoformat(),
        "last_backup_receipt": "a" * 64,
        "worker_image": "registry.example/stpd@sha256:" + "b" * 64,
    }


def test_capacity_cli_requires_explicit_peak_and_preserves_unknown(monkeypatch, tmp_path):
    arguments = [
        "--capacity",
        "--config",
        str(tmp_path / "deployment.env"),
        "--image-store",
        str(tmp_path),
    ]
    for extra in (
        [],
        ["--additional-bytes", "0"],
        ["--additional-bytes", "-1", "--additional-inodes", "0"],
    ):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            assert preflight.main([*arguments, *extra]) == 2
        assert (
            json.loads(output.getvalue())["error"]
            == "explicit_nonnegative_additional_capacity_required"
        )
    reports = []
    monkeypatch.setattr(
        preflight,
        "check_capacity",
        lambda *a, **k: (
            reports.append(k)
            or {
                "status": "unknown",
                "filesystems": [],
            }
        ),
    )
    with contextlib.redirect_stdout(io.StringIO()) as output:
        assert (
            preflight.main([*arguments, "--additional-bytes", "0", "--additional-inodes", "0"]) == 2
        )
    assert reports == [{"additional_bytes": 0, "additional_inodes": 0}]
    assert json.loads(output.getvalue())["capacity"]["status"] == "unknown"
    # Exact owner can be loaded by production host Python without research site packages.
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "import preflight; print(preflight.capacity_owner().RESERVE_BYTES)",
        ],
        cwd=Path(preflight.__file__).parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and result.stdout.strip() == str(6 * 1024**3)


def test_running_and_terminal_safe_projection_follow_atomic_owner_without_secrets(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "backup-status.json"
    value = status()
    prior = os.umask(0o077)
    try:
        assert maintenance.write_status(path, {**value, "secret": "DO_NOT_PUBLISH"})
    finally:
        os.umask(prior)
    public = tmp_path / "safe-status/backup-status.json"
    first = json.loads(public.read_bytes())
    assert "DO_NOT_PUBLISH" not in public.read_text() and "secret" not in first
    assert first["maximum_age_seconds"] == maintenance.MAX_AGE_SECONDS
    running = {**value, "last_status": "running", "last_error": "PRIVATE_PATH_OR_STDERR"}
    assert maintenance.write_status(path, running)
    assert json.loads(public.read_bytes())["last_status"] == "running"
    assert json.loads(public.read_bytes())["last_backup_receipt"] == value["last_backup_receipt"]
    reader = ConsoleRoutes.__new__(ConsoleRoutes)
    reader.backup_status = public
    assert reader.backup()["freshness"] == "attention"  # An interrupted new attempt is not green.
    assert maintenance.write_status(path, value)
    assert reader.backup()["freshness"] == "ok"
    old = {**value, "last_success_at": (datetime.now(UTC) - timedelta(hours=27)).isoformat()}
    assert maintenance.write_status(path, old)
    assert reader.backup()["freshness"] == "attention"
    if os.name != "nt":
        assert public.stat().st_mode & 0o777 == 0o644
        assert public.parent.stat().st_mode & 0o777 == 0o755
        assert tmp_path.stat().st_mode & 0o777 == 0o700


def test_safe_projection_failure_preserves_private_backup_success_and_old_projection(tmp_path):
    tmp_path.chmod(0o700)
    path, value = tmp_path / "backup-status.json", status()
    assert maintenance.write_status(path, value)
    public = tmp_path / "safe-status/backup-status.json"
    prior = public.read_bytes()
    with patch.object(maintenance, "publish_safe_status", side_effect=OSError("PRIVATE_ERROR")):
        assert not maintenance.write_status(path, {**value, "last_status": "running"})
    assert public.read_bytes() == prior
    assert json.loads(path.read_bytes())["last_status"] == "running"
    with pytest.raises(ValueError):
        maintenance.publish_safe_status(path, {**value, "last_backup_receipt": "PRIVATE_RAW_VALUE"})
    with pytest.raises(ValueError):
        maintenance.publish_safe_status(
            path,
            {
                "schema": maintenance.SCHEMA,
                "last_status": "success",
                "last_success_at": value["last_success_at"],
            },
        )
    reader = ConsoleRoutes.__new__(ConsoleRoutes)
    reader.backup_status = path
    path.write_text(
        json.dumps(
            {
                "schema": maintenance.SCHEMA,
                "last_status": "success",
                "last_success_at": value["last_success_at"],
                "maximum_age_seconds": maintenance.MAX_AGE_SECONDS,
            }
        )
    )
    assert reader.backup()["availability"] == "unavailable"
    path.write_text(json.dumps({**value, "last_backup_receipt": "PRIVATE_RAW_VALUE"}))
    assert reader.backup()["availability"] == "unavailable"
    assert "PRIVATE_RAW_VALUE" not in json.dumps(reader.backup())
    assert maintenance.health(json.loads(path.read_bytes()))["backup_health"] != "PASS"
    path.write_text(json.dumps({**value, "maximum_age_seconds": 365 * 24 * 3600}))
    assert reader.backup()["availability"] == "unavailable"
    assert maintenance.health(json.loads(path.read_bytes()))["backup_health"] != "PASS"


def test_status_writer_rejects_non_root_linux_ownership(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(maintenance, "owner_uid", lambda path: 501)
    monkeypatch.setattr(maintenance.platform, "system", lambda: "Linux")
    path = tmp_path / "status.json"
    with pytest.raises(preflight.PreflightError, match="private_root"):
        maintenance.write_status(path, status())
    with pytest.raises(preflight.PreflightError, match="private_root"):
        maintenance.publish_safe_status(path, status())
    assert not path.exists()


def test_host_preflight_requires_private_root_owner_and_prepared_readable_directory(
    tmp_path,
    monkeypatch,
):
    private = tmp_path / "maintenance"
    private.mkdir()
    private.chmod(0o700)
    safe = private / "safe-status"
    monkeypatch.setattr(preflight, "SAFE_STATUS_DIRECTORY", safe)
    monkeypatch.setattr(preflight.platform, "system", lambda: "Linux")
    monkeypatch.setattr(preflight.platform, "machine", lambda: "amd64")
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/test/docker")
    monkeypatch.setattr(preflight, "owner_uid", lambda path: 0)
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            [],
            0,
            "2.30.0",
            "",
        ),
    )
    monkeypatch.setattr(preflight.os, "sysconf", lambda name: 4096, raising=False)
    with pytest.raises(preflight.PreflightError, match="preparation"):
        preflight.host_checks()
    safe.mkdir()
    safe.chmod(0o755)
    assert preflight.host_checks()["host"] == "PASS"
    private.chmod(0o755)
    with pytest.raises(preflight.PreflightError, match="private_backup_status"):
        preflight.host_checks()
    private.chmod(0o700)
    monkeypatch.setattr(preflight, "owner_uid", lambda path: 501)
    with pytest.raises(preflight.PreflightError, match="private_backup_status"):
        preflight.host_checks()


def test_maintenance_status_is_read_only_and_does_not_block_backup_for_capacity(
    tmp_path, monkeypatch
):
    tmp_path.chmod(0o700)
    path, value = tmp_path / "status.json", status()
    maintenance.write_status(path, value)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    monkeypatch.setattr(maintenance, "check_capacity", lambda *a, **k: {"status": "attention"})
    with contextlib.redirect_stdout(io.StringIO()) as output:
        assert maintenance.main(["status", "--status-file", str(path)]) == 2
    assert json.loads(output.getvalue())["backup_health"] == "PASS"
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    monkeypatch.setattr(
        maintenance, "run_backup", lambda *a: {**value, "status_projection": "published"}
    )
    monkeypatch.setattr(
        maintenance, "check_capacity", lambda *a, **k: pytest.fail("backup blocked")
    )
    with contextlib.redirect_stdout(io.StringIO()):
        assert maintenance.main(["backup", "--status-file", str(path)]) == 0
