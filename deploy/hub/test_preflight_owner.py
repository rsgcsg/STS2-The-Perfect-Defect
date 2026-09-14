"""SQLite WAL ownership: host privilege scope and a real Linux-root regression."""

from __future__ import annotations

import os
import platform
import sqlite3
import tempfile
import threading
from contextlib import closing
from pathlib import Path

import preflight
import pytest
import test_deployment as deployment
from test_support import PosixPermissionFixture

browser_environment = deployment.PreflightTests.browser_environment


@pytest.fixture(autouse=True)
def portable_permissions():
    fixture = PosixPermissionFixture()
    fixture.setUp()
    try:
        yield
    finally:
        fixture.doCleanups()


@pytest.fixture
def owner_scope(monkeypatch):
    current = {"uid": 0, "gid": 0, "groups": [0, 7], "events": []}
    monkeypatch.setattr(preflight.platform, "system", lambda: "Linux")
    monkeypatch.setattr(preflight, "owner_uid", lambda path: 10001)
    monkeypatch.setattr(threading, "active_count", lambda: 1)
    for field, getter, setter in (
        ("uid", "geteuid", "seteuid"),
        ("gid", "getegid", "setegid"),
        ("groups", "getgroups", "setgroups"),
    ):
        monkeypatch.setattr(preflight.os, getter, lambda key=field: current[key], raising=False)

        def update(value, key=field):
            current["events"].append((key, value))
            current[key] = value

        monkeypatch.setattr(preflight.os, setter, update, raising=False)
    return current


def test_owner_switch_partial_failure_restores_operator_before_any_query(
    tmp_path,
    monkeypatch,
    owner_scope,
):
    path = deployment.PreflightTests.membership_database(tmp_path)
    switch = preflight.os.seteuid

    def fail_drop(uid):
        if uid == 10001:
            raise PermissionError("synthetic cannot drop")
        switch(uid)

    monkeypatch.setattr(preflight.os, "seteuid", fail_drop)
    monkeypatch.setattr(preflight.sqlite3, "connect", lambda *a, **k: pytest.fail("opened as root"))
    with pytest.raises(PermissionError):
        preflight.check_console(browser_environment(), tmp_path)
    assert (owner_scope["uid"], owner_scope["gid"], owner_scope["groups"]) == (0, 0, [0, 7])
    assert owner_scope["events"] == [
        ("groups", []),
        ("gid", path.stat().st_gid),
        ("uid", 0),
        ("gid", 0),
        ("groups", [0, 7]),
    ]


@pytest.mark.parametrize("query_failure", [False, True])
def test_real_wal_open_and_close_are_inside_owner_scope(
    tmp_path,
    monkeypatch,
    owner_scope,
    query_failure,
):
    root = tmp_path.resolve()
    path = deployment.PreflightTests.membership_database(root)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("PRAGMA journal_mode=WAL")
        if query_failure:
            db.execute("DROP TABLE identity_members")
    assert not Path(str(path) + "-wal").exists()
    assert not Path(str(path) + "-shm").exists()
    before = path.read_bytes()
    original = sqlite3.connect
    events = owner_scope["events"]

    class Connection:
        def __init__(self, *args, **kwargs):
            assert owner_scope["uid"] == 10001
            assert args[0].endswith("?mode=ro") and "immutable" not in args[0]
            events.append(("connect", owner_scope["uid"]))
            self.db = original(*args, **kwargs)

        def execute(self, *args):
            assert owner_scope["uid"] == 10001
            return self.db.execute(*args)

        def close(self):
            assert owner_scope["uid"] == 10001
            self.db.close()
            events.append(("closed", owner_scope["uid"]))

    monkeypatch.setattr(preflight.sqlite3, "connect", Connection)
    if query_failure:
        with pytest.raises(preflight.PreflightError, match="unreadable_or_incompatible"):
            preflight.check_console(browser_environment(), root)
    else:
        assert (
            preflight.check_console(browser_environment(), root)["membership"]
            == "hub_operations_active_admin"
        )
    assert path.read_bytes() == before
    assert events.index(("closed", 10001)) < events.index(("uid", 0))
    assert (owner_scope["uid"], owner_scope["gid"], owner_scope["groups"]) == (0, 0, [0, 7])


def test_threaded_or_unprivileged_operator_cannot_open_database(
    tmp_path,
    monkeypatch,
    owner_scope,
):
    deployment.PreflightTests.membership_database(tmp_path)
    monkeypatch.setattr(preflight.sqlite3, "connect", lambda *a, **k: pytest.fail("opened"))
    monkeypatch.setattr(threading, "active_count", lambda: 2)
    with pytest.raises(preflight.PreflightError, match="single_threaded"):
        preflight.check_console(browser_environment(), tmp_path)
    owner_scope["uid"] = 1000
    with pytest.raises(preflight.PreflightError, match="root_or_database_owner"):
        preflight.check_console(browser_environment(), tmp_path)


@pytest.mark.skipif(
    platform.system() != "Linux" or getattr(os, "geteuid", lambda: -1)() != 0,
    reason="actual UID transition requires a Linux root qualification process",
)
def test_linux_root_preflight_creates_only_hub_owned_sidecars_and_preserves_wal():
    # This is synthetic local state. Run explicitly as root on Linux qualification;
    # ordinary portable CI neither invokes sudo nor touches live Hub state.
    original_identity = (os.geteuid(), os.getegid(), os.getgroups())
    with tempfile.TemporaryDirectory(prefix="stpd-preflight-owner-") as directory:
        root = Path(directory).resolve()
        path = deployment.PreflightTests.membership_database(root)
        with closing(sqlite3.connect(path)) as db:
            db.execute("PRAGMA journal_mode=WAL")
        assert set(root.iterdir()) == {path}
        os.chown(root, 10001, 10001)
        os.chown(path, 10001, 10001)
        before = path.read_bytes()
        assert (
            preflight.check_console(browser_environment(), root)["membership"]
            == "hub_operations_active_admin"
        )
        assert path.read_bytes() == before
        assert {p.name for p in root.iterdir()} == {
            "operations.sqlite",
            "operations.sqlite-wal",
            "operations.sqlite-shm",
        }
        for item in root.iterdir():
            assert item.stat().st_uid == 10001 and item.stat().st_gid == 10001
            assert item.stat().st_mode & 0o777 == 0o600
        assert (os.geteuid(), os.getegid(), os.getgroups()) == original_identity
        with preflight.membership_reader_owner(path), closing(sqlite3.connect(path)) as writer:
            writer.execute("UPDATE identity_members SET status='disabled'")
            writer.commit()
            # The still-open writer retains current WAL; preflight must read it.
            with pytest.raises(preflight.PreflightError, match="active_admin_required"):
                preflight.check_console(browser_environment(), root)
        assert (os.geteuid(), os.getegid(), os.getgroups()) == original_identity
