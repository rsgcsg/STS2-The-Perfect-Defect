"""Operational reserve, shared-filesystem accounting and actual parent deferral."""

from __future__ import annotations

import json
import os
import threading
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_hub_console import service
from test_hub_uploads import fixture

from stpd.hub import capacity, verification_worker
from stpd.hub.console_auth import ConsolePrincipal
from stpd.hub.console_routes import ConsoleRoutes

GIB = 1024**3
Disk = namedtuple("Disk", "total used free")


def measured(monkeypatch, *, free=16 * GIB, inodes=500_000):
    monkeypatch.setattr(
        capacity.shutil, "disk_usage", lambda path: Disk(40 * GIB, 40 * GIB - free, free)
    )
    monkeypatch.setattr(
        capacity.os,
        "statvfs",
        lambda path: SimpleNamespace(
            f_files=1_000_000,
            f_favail=inodes,
            f_ffree=inodes + 100,
        ),
        raising=False,
    )


def test_capacity_requires_available_bytes_and_inodes_and_preserves_unknown(tmp_path, monkeypatch):
    measured(monkeypatch, free=capacity.RESERVE_BYTES, inodes=capacity.RESERVE_INODES)
    assert capacity.filesystem_capacity(tmp_path)["status"] == "ok"
    assert capacity.filesystem_capacity(tmp_path, additional_bytes=1)["status"] == "attention"
    assert capacity.filesystem_capacity(tmp_path, additional_inodes=1)["status"] == "attention"
    measured(monkeypatch, free=3 * GIB)
    value = capacity.filesystem_capacity(tmp_path)
    assert value["reasons"] == ["free_bytes_below_reserve"]
    assert str(tmp_path) not in json.dumps(value)
    measured(monkeypatch)
    monkeypatch.setattr(capacity.os, "statvfs", None)
    unknown = capacity.filesystem_capacity(tmp_path)
    assert unknown["status"] == "unknown" and unknown["free_inodes"] is None
    assert capacity.filesystem_capacity(tmp_path / "absent")["status"] == "unknown"


def test_shared_filesystem_keeps_existing_images_and_counts_additional_once(tmp_path, monkeypatch):
    state, images = tmp_path / "state", tmp_path / "images"
    state.mkdir()
    images.mkdir()
    measured(monkeypatch, free=capacity.RESERVE_BYTES + GIB)
    report = capacity.host_capacity(state, images, additional_bytes=GIB, additional_inodes=0)
    assert report["status"] == "ok" and report["same_filesystem"] is True
    assert len(report["filesystems"]) == 1
    assert report["filesystems"][0]["required_free_bytes"] == 7 * GIB
    assert (
        capacity.host_capacity(
            state,
            images,
            additional_bytes=GIB + 1,
            additional_inodes=0,
        )["status"]
        == "attention"
    )
    assert list(state.iterdir()) == list(images.iterdir()) == []
    original = Path.stat

    def different_device(path, **kwargs):
        value = original(path, **kwargs)
        if path == images:
            return os.stat_result((value.st_mode, value.st_ino, value.st_dev + 1, *value[3:]))
        return value

    monkeypatch.setattr(Path, "stat", different_device)
    split = capacity.host_capacity(state, images, additional_bytes=GIB, additional_inodes=1)
    assert split["same_filesystem"] is False and len(split["filesystems"]) == 2
    assert split["filesystems"][0]["additional_bytes"] == 0
    assert split["filesystems"][1]["required_free_bytes"] == 2 * GIB


@pytest.mark.parametrize("status", ["attention", "unknown"])
def test_actual_parent_capacity_deferral_never_claims_or_consumes_attempt(
    tmp_path,
    monkeypatch,
    status,
):
    owner, intent, _ = fixture(tmp_path)
    upload = owner.intent("one", intent)["upload_id"]
    owner.operations.request_verification(upload)
    before = owner.operations.upload(upload)
    monkeypatch.setattr(verification_worker.sys, "platform", "linux")
    monkeypatch.setattr(
        verification_worker, "filesystem_capacity", lambda *a, **k: {"status": status}
    )
    monkeypatch.setattr(
        verification_worker, "_run_verifier", lambda *a: pytest.fail("child started")
    )
    monkeypatch.setattr(
        verification_worker.tempfile,
        "TemporaryDirectory",
        lambda *a, **k: pytest.fail("scratch allocated"),
    )
    shutdown = threading.Event()
    for _ in range(6):
        assert (
            verification_worker.supervise_pending_upload(
                owner.operations,
                upload,
                [],
                shutdown,
            )
            == "capacity_deferred"
        )
    assert owner.operations.upload(upload) == before
    # Real process failures still use the existing owning retry disposition.
    monkeypatch.setattr(verification_worker, "run_verifier", lambda *a, **k: False)
    assert (
        verification_worker.supervise_pending_upload(
            owner.operations,
            upload,
            [],
            shutdown,
        )
        == "retry_pending"
    )
    assert owner.operations.upload(upload)["verify_attempts"] == 1
    assert owner.operations.upload(upload)["status"] == "verification_pending"


def test_deep_valid_transfer_counts_parent_inodes_before_parent_dispatch(tmp_path, monkeypatch):
    from sts2_platform_evidence import DirectoryTransferManifest
    from sts2_platform_evidence.transfer import TransferFile

    owner, intent, _ = fixture(tmp_path)
    files = tuple(
        TransferFile("/".join([str(index)] * 1000) + "/file", 0, "0" * 64) for index in range(110)
    )
    transfer = DirectoryTransferManifest(
        "a" * 64, "human-session-bundle", tuple(sorted(files, key=lambda item: item.path)),
    )
    intent["transfer_manifest"] = transfer.to_dict()
    upload = owner.intent("one", intent)["upload_id"]
    owner.operations.request_verification(upload)
    monkeypatch.setattr(verification_worker.sys, "platform", "linux")
    requests = []

    def observed(path, **kwargs):
        requests.append(kwargs["reserve_inodes"])
        return {"status": "attention"}

    monkeypatch.setattr(verification_worker, "filesystem_capacity", observed)
    assert (
        verification_worker.supervise_pending_upload(
            owner.operations,
            upload,
            [],
            threading.Event(),
        )
        == "capacity_deferred"
    )
    assert requests == [capacity.IMAGE_RESERVE_INODES + 110 * 1001]
    assert owner.operations.upload(upload)["verify_attempts"] == 0


def test_system_storage_keeps_old_fields_without_changing_health_or_member_scope(
    tmp_path, monkeypatch
):
    owner = service(tmp_path)
    measured(monkeypatch, free=GIB)
    value = ConsoleRoutes(owner, 0).system(ConsolePrincipal("admin", ()))
    assert value["storage"]["scope"] == "hub_state_filesystem"
    assert value["storage"]["total_bytes"] == 40 * GIB
    assert value["storage"]["free_bytes"] == GIB
    assert value["storage"]["capacity"]["status"] == "attention"
    assert "storage" not in ConsoleRoutes(owner, 0).system(ConsolePrincipal("member", ()))
