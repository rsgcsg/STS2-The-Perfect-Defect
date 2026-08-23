from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from stpd.data import SplitAssignment
from stpd.experiments.s1_smoke import (
    DEFAULT_CONFIG,
    S1PreparationError,
    _select_train_records,
    _validate_config,
    _verify_checksum_directory,
    run_s1_smoke,
)


def _config() -> dict:
    return json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))


def _records(count: int) -> tuple[list[dict], dict[str, SplitAssignment]]:
    records = []
    assignments = {}
    for index in range(count):
        episode = f"episode-{index:04d}"
        records.append(
            {
                "transition_id": f"transition-{index:04d}",
                "episode_id": episode,
                "eligibility": {
                    "rank": True,
                    "rank_mode": "full_listwise",
                    "legal_action_completeness": "complete",
                },
            }
        )
        assignments[episode] = SplitAssignment(episode, f"root-{index:04d}", "train")
    return records, assignments


def test_s1_config_freezes_owner_and_data_boundaries() -> None:
    config = _config()
    _validate_config(config)

    drifted = copy.deepcopy(config)
    drifted["data"]["minimum_unified_records"] = 1499
    with pytest.raises(S1PreparationError, match="gates must remain"):
        _validate_config(drifted)

    drifted = copy.deepcopy(config)
    drifted["boundaries"]["gold_test_allowed"] = True
    with pytest.raises(S1PreparationError, match="must forbid"):
        _validate_config(drifted)


def test_s1_train_selection_is_hash_sorted_and_requires_1000_rows() -> None:
    records, assignments = _records(1000)
    selected = _select_train_records(list(reversed(records)), assignments, _config())

    assert len(selected) == 1000
    assert selected == sorted(selected, key=lambda item: hashlib.sha256(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest())

    with pytest.raises(S1PreparationError, match="at least 1000"):
        _select_train_records(records[:-1], assignments, _config())


def test_s1_checksum_inventory_fails_closed_on_drift(tmp_path: Path) -> None:
    payload = tmp_path / "payload.json"
    payload.write_text("{}\n", encoding="utf-8")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    inventory = tmp_path / "checksums.sha256"
    inventory.write_text(f"{digest}  payload.json\n", encoding="utf-8")

    assert _verify_checksum_directory(tmp_path) == hashlib.sha256(
        inventory.read_bytes()
    ).hexdigest()
    payload.write_text("drift\n", encoding="utf-8")
    with pytest.raises(S1PreparationError, match="checksum mismatch"):
        _verify_checksum_directory(tmp_path)


def test_s1_run_requires_exact_owner_ack_before_any_training(tmp_path: Path) -> None:
    with pytest.raises(S1PreparationError, match="owner acknowledgement"):
        run_s1_smoke(
            ready_path=tmp_path / "missing.json",
            ready_sha256="0" * 64,
            owner_ack="not-authorized",
        )
