"""Deterministic root-group split assignment with no transition-level leakage."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

SplitName = Literal["train", "dev", "test"]


@dataclass(frozen=True)
class SplitAssignment:
    episode_id: str
    root_id: str
    split: SplitName


def _bucket(root_id: str, salt: str) -> int:
    digest = hashlib.sha256(f"{salt}\0{root_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 10_000


def assign_episode_splits(
    records: Iterable[Mapping[str, Any]],
    *,
    salt: str,
    train_ratio: int = 8000,
    dev_ratio: int = 1000,
    test_ratio: int = 1000,
    root_field: str = "seed",
) -> dict[str, SplitAssignment]:
    """Assign every episode sharing one seed/root to exactly one stable split."""

    if train_ratio + dev_ratio + test_ratio != 10_000:
        raise ValueError("split ratios must sum to 10000 basis points")
    if not salt:
        raise ValueError("split salt must be explicit")
    episode_roots: dict[str, str] = {}
    for record in records:
        episode_id = str(record.get("episode_id", ""))
        root_id = str(record.get(root_field, ""))
        if not episode_id or not root_id:
            raise ValueError(f"record missing episode_id or {root_field}")
        previous = episode_roots.setdefault(episode_id, root_id)
        if previous != root_id:
            raise ValueError(f"episode {episode_id} spans multiple roots")
    root_splits: dict[str, SplitName] = {}
    for root_id in sorted(set(episode_roots.values())):
        value = _bucket(root_id, salt)
        if value < train_ratio:
            split: SplitName = "train"
        elif value < train_ratio + dev_ratio:
            split = "dev"
        else:
            split = "test"
        root_splits[root_id] = split
    return {
        episode_id: SplitAssignment(episode_id, root_id, root_splits[root_id])
        for episode_id, root_id in sorted(episode_roots.items())
    }
