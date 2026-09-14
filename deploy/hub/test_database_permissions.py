"""Real producer/bootstrap permissions; never manually chmod the fresh database."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import preflight
import pytest

from stpd.hub.database import Operations, create_private_database

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Linux host POSIX permission contract")

ISSUER = "https://team.cloudflareaccess.com"
BROWSER = {"STPD_ACCESS_ISSUER": ISSUER, "STPD_ACCESS_AUDIENCE": "a" * 64}


@pytest.mark.parametrize("creation_umask", [0o000, 0o022])
def test_real_fresh_cli_bootstrap_and_snapshot_are_private_before_preflight(
    tmp_path,
    monkeypatch,
    creation_umask,
):
    state = tmp_path.resolve()
    state.chmod(0o700)
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "stpd.hub", "members-bootstrap", "--state", str(state)],
        cwd=root,
        env={
            **os.environ,
            "STPD_ACCESS_ISSUER": ISSUER,
            "STPD_BOOTSTRAP_ADMIN_EMAIL": "operator@example.invalid",
        },
        umask=creation_umask,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    path = state / "operations.sqlite"
    assert path.stat().st_mode & 0o777 == 0o600
    # Current OS owner is used by the actual producer; the portable inspection only
    # substitutes deployment UID, not the file's measured POSIX permission bits.
    monkeypatch.setattr(preflight, "owner_uid", lambda path: 10001)
    monkeypatch.setattr(preflight.os, "geteuid", lambda: 10001)
    assert preflight.check_console(BROWSER, state)["browser_console"] == "bootstrap_pending"
    with Operations(path).transaction() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        for suffix in ("", "-wal", "-shm"):
            assert Path(str(path) + suffix).stat().st_mode & 0o777 == 0o600
    snapshot = state / "snapshot.sqlite"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; from stpd.hub.database import Operations; "
            "import sys; Operations(Path(sys.argv[1])).backup(Path(sys.argv[2]))",
            str(path),
            str(snapshot),
        ],
        cwd=root,
        umask=creation_umask,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert snapshot.stat().st_mode & 0o777 == 0o600
    assert preflight.check_backup(snapshot)["restore_mode"] == "paused"
    assert not Path(str(snapshot) + "-wal").exists()
    assert not Path(str(snapshot) + "-shm").exists()
    # A legacy deployment still requires explicit permission repair, never inspection magic.
    path.chmod(0o644)
    Operations(path)
    assert path.stat().st_mode & 0o777 == 0o644
    with pytest.raises(preflight.PreflightError, match="private_uid_10001"):
        preflight.check_console(BROWSER, state)
    assert path.stat().st_mode & 0o777 == 0o644


def test_existing_file_or_symlink_is_not_overwritten_or_chmodded(tmp_path):
    existing = tmp_path / "existing.sqlite"
    existing.write_bytes(b"existing owner evidence")
    existing.chmod(0o644)
    for path in (existing, tmp_path / "link.sqlite"):
        if path != existing:
            path.symlink_to(existing)
        with pytest.raises(FileExistsError):
            create_private_database(path)
        assert existing.read_bytes() == b"existing owner evidence"
        assert existing.stat().st_mode & 0o777 == 0o644


def test_transactions_do_not_recreate_a_missing_operations_database(tmp_path):
    path = tmp_path / "operations.sqlite"
    operations = Operations(path)
    path.unlink()
    with pytest.raises(sqlite3.OperationalError):
        operations.paused()
    assert not path.exists()
