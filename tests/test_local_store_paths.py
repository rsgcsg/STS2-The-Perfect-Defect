from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from stpd.storage.blobs import StoreError
from stpd.storage.local import LocalBlobStore


def test_validated_keys_do_not_resolve_mutable_hard_link_names(tmp_path: Path, monkeypatch) -> None:
    store = LocalBlobStore(tmp_path)

    def forbidden_resolve(*args, **kwargs):
        raise AssertionError("a validated object key must not resolve a mutable leaf")

    monkeypatch.setattr(Path, "resolve", forbidden_resolve)
    assert store.put_if_absent("objects/a", b"content")
    assert not store.put_if_absent("objects/a", b"content")
    assert store.get("objects/a") == b"content"


def test_windows_reparse_point_is_rejected_without_following_it(
    tmp_path: Path, monkeypatch
) -> None:
    store = LocalBlobStore(tmp_path)
    original = os.lstat

    def lstat(path, *args, **kwargs):
        if Path(path) == tmp_path / "objects":
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", lstat)
    with pytest.raises(StoreError, match="reparse_object_path"):
        store.put_if_absent("objects/a", b"content")


def test_repeated_concurrent_publish_is_exact_and_idempotent(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for index in range(20):
            key = f"objects/{index}"
            results = list(pool.map(lambda _, key=key: store.put_if_absent(key, b"same"), range(16)))
            assert sum(results) == 1
            assert store.get(key) == b"same"
    assert not list(tmp_path.rglob(".pending-*"))
