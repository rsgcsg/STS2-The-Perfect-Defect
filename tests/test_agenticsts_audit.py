from __future__ import annotations

import gzip
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from stpd.data.agenticsts_audit import (
    audit_agenticsts_trajectory,
    load_agenticsts_source_pin,
)

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "configs" / "v0" / "data" / "agenticsts-trajectories.json"


def _state(step: int, *, complete_catalog: bool = False) -> dict[str, Any]:
    value: dict[str, Any] = {
        "event": "state",
        "step": step,
        "state_type": "monster",
        "deck": [{"name": "Defend"}],
        "combat": {
            "round": step,
            "is_play_phase": True,
            "player": {
                "hand": [
                    {
                        "index": 0,
                        "name": "Defend",
                        "playable": True,
                        "target_type": "Self",
                    }
                ]
            },
            "enemies": [{"name": "Slime", "hp": 10}],
        },
    }
    if complete_catalog:
        value["legal_actions"] = [{"action": "end_turn"}]
        value["eligibility"] = {"legal_action_completeness": "complete"}
    return value


def _write_gzip(path: Path, rows: list[Mapping[str, Any]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _history() -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "profile_hash": "profile-hash",
        "model_profile": {"strategic_model": "historical-model"},
    }


def test_checked_in_agenticsts_source_pin_is_immutable() -> None:
    pin = load_agenticsts_source_pin(PIN)

    assert pin.revision == "20f5170c420584935ec20e004498b4d4a3621f8b"
    assert pin.license == "CC-BY-4.0"
    assert pin.expected_trajectory_files == 305


def test_raw_combat_state_does_not_invent_a_legal_catalog(tmp_path: Path) -> None:
    path = tmp_path / "trajectory.jsonl.gz"
    _write_gzip(
        path,
        [
            _state(1),
            {
                "event": "action_result",
                "step": 1,
                "action": "end_turn",
                "status": "ok",
                "mcp_stable": True,
            },
            {
                "event": "decision",
                "step": 1,
                "state_type": "monster",
                "action": {"action": "end_turn"},
                "source": "llm",
            },
            _state(2),
        ],
    )

    audit = audit_agenticsts_trajectory(
        path,
        {"run_id": "run-1", "game_version": "v0.103.1"},
        _history(),
    )

    assert audit.combat_decision_records == 1
    assert audit.player_visible_state_records == 1
    assert audit.stable_successor_records == 1
    assert audit.complete_legal_action_catalog_records == 0
    assert audit.rank_eligible_accepted_records == 0
    assert audit.rejection_reasons["missing_complete_legal_action_catalog"] == 1


def test_audit_accepts_only_when_every_explicit_requirement_exists(tmp_path: Path) -> None:
    path = tmp_path / "trajectory.jsonl.gz"
    first = _state(1, complete_catalog=True)
    first["environment"] = {
        "game_version": "historical-v1",
        "game_commit": "historical-commit",
        "game_artifact_sha256": "1" * 64,
        "game_artifact_mvid": "11111111-1111-1111-1111-111111111111",
        "host_kind": "historical-host",
        "host_source_revision": "historical-revision",
        "host_source_digest_sha256": "2" * 64,
        "host_artifact_sha256": "3" * 64,
        "host_artifact_mvid": "22222222-2222-2222-2222-222222222222",
        "player_environment_protocol": "historical-protocol",
        "player_environment_implementation": "historical-environment",
        "player_environment_revision": "historical-environment-revision",
        "player_environment_digest_sha256": "4" * 64,
        "information_policy_id": "historical-player-visible",
    }
    _write_gzip(
        path,
        [
            first,
            {
                "event": "action_result",
                "step": 1,
                "action": "end_turn",
                "status": "ok",
                "mcp_stable": True,
            },
            {
                "event": "decision",
                "step": 1,
                "seed": "historical-seed",
                "state_type": "monster",
                "action": {"action": "end_turn"},
                "source": "llm",
            },
            _state(2),
        ],
    )

    audit = audit_agenticsts_trajectory(
        path,
        {"run_id": "run-1", "game_version": "historical-v1"},
        _history(),
    )

    assert audit.complete_legal_action_catalog_records == 1
    assert audit.uniquely_resolvable_chosen_action_records == 1
    assert audit.exact_environment_identity_records == 1
    assert audit.rank_eligible_accepted_records == 1
    assert not audit.rejection_reasons
