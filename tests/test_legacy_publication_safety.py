"""Historical lifecycle bytes stay compatible while publication fails closed."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from stpd.data.training_handoff import (
    TrainingHandoffError,
    _atomic_copy,
    _atomic_write,
    _load_manifest,
    _logical_path,
)


def test_publication_is_concurrent_idempotent_and_never_overwrites(tmp_path: Path) -> None:
    destination = tmp_path / "immutable.json"
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: _atomic_write(destination, "same\n"), range(16)))
    assert destination.read_bytes() == b"same\n"
    with pytest.raises(TrainingHandoffError, match="collision"):
        _atomic_write(destination, "different\n")
    assert destination.read_bytes() == b"same\n"
    assert not list(tmp_path.glob(".immutable.json.*"))


def test_changed_copy_never_publishes_a_wrong_digest(tmp_path: Path) -> None:
    source, destination = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"changed")
    expected = hashlib.sha256(b"original").hexdigest()
    with pytest.raises(TrainingHandoffError, match="source changed"):
        _atomic_copy(source, destination, expected)
    assert not destination.exists()
    destination.write_bytes(b"existing")
    with pytest.raises(TrainingHandoffError, match="collision"):
        _atomic_copy(source, destination, hashlib.sha256(b"changed").hexdigest())
    assert destination.read_bytes() == b"existing"


@pytest.mark.parametrize("value", ["../escape", "a/../b", "a\\b", "C:/file", "/file", "a//b"])
def test_logical_paths_are_host_independent(value: str) -> None:
    with pytest.raises(TrainingHandoffError):
        _logical_path(value)


def test_manifest_id_is_checked_before_opening_a_path(tmp_path: Path) -> None:
    with pytest.raises(TrainingHandoffError, match="digest"):
        _load_manifest(tmp_path, "../../outside")
