from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from stpd.contracts import ContractError
from stpd.environment import collect_managed_runtime


def _ready() -> dict[str, Any]:
    exact_game = {
        "platform": "darwin",
        "architecture": "arm64",
        "version": "v0.111.0",
        "commit": "41cef1ea",
        "runtime_main_assembly_hash": 1010476334,
        "sts2_dll_sha256": "c" * 64,
        "godotsharp_dll_sha256": "e" * 64,
    }
    return {
        "protocol": "sts2.headless/managed-player-environment-driver-1",
        "headless": {
            "source_revision": "headless-revision",
            "source_worktree_status": "clean",
            "source_digest_sha256": "d" * 64,
        },
        "candidate_manifest": {
            "exact_game": exact_game,
            "expected_build": {
                "artifact_sha256": "a" * 64,
                "artifact_mvid": "22222222-2222-4222-8222-222222222222",
            },
        },
        "exact_game": exact_game,
        "candidate_build": {
            "upstream_revision": "managed-upstream",
            "source_patch_sha256": "b" * 64,
            "artifact_sha256": "a" * 64,
            "artifact_mvid": "22222222-2222-4222-8222-222222222222",
            "runtime_sts2_sha256": "c" * 64,
        },
        "runtime_identity": {
            "host_assembly_sha256": "a" * 64,
            "host_module_mvid": "22222222-2222-4222-8222-222222222222",
            "sts2_assembly_sha256": "c" * 64,
            "sts2_module_mvid": "11111111-1111-4111-8111-111111111111",
        },
        "adapter_runtime_instance_id": "runtime",
        "environment_fingerprint": "fingerprint",
    }


def _base_snapshot(snapshot_id: str, sequence: int, kind: str) -> dict[str, Any]:
    return {
        "protocol_version": "1.0.0",
        "snapshot_id": snapshot_id,
        "sequence": sequence,
        "status": "interactive",
        "persistent": {"content": {"player": {"hp": 80}, "run": {"floor": 1}}},
        "interaction": {
            "interaction_id": f"interaction-{snapshot_id}",
            "kind": kind,
            "stage": "current",
            "content": {"surface": {"kind": kind}, "context": {"kind": "run"}},
        },
        "referents": [],
        "bound_actions": {
            "status": "complete",
            "actions": [],
            "materialized_count": 0,
            "total_count": 0,
        },
        "reads": [],
        "completeness": {"status": "complete"},
        "session": {
            "runtime_instance_id": "runtime",
            "environment_fingerprint": "fingerprint",
        },
        "information_policy": {"id": "player_visible_v1"},
    }


def _map_snapshot() -> dict[str, Any]:
    snapshot = _base_snapshot("map-0", 0, "map_navigation")
    snapshot["referents"] = [
        {
            "referent_id": "map-node-1",
            "role": "option",
            "kind": "entity",
            "label": "Monster",
            "properties": {"type": "monster", "row": 0, "col": 0},
        }
    ]
    snapshot["bound_actions"].update(
        {
            "actions": [
                {
                    "bound_action_id": "bound-map",
                    "verb": "activate",
                    "subject_referent_id": "map-node-1",
                    "arguments": [],
                    "label": "Enter Monster",
                }
            ],
            "materialized_count": 1,
            "total_count": 1,
        }
    )
    return snapshot


def _combat_snapshot() -> dict[str, Any]:
    snapshot = _base_snapshot("combat-1", 1, "combat_turn")
    snapshot["interaction"]["content"]["context"] = {"kind": "combat"}
    snapshot["referents"] = [
        {
            "referent_id": "card-1",
            "role": "hand_card",
            "kind": "entity",
            "label": "Defend",
            "properties": {
                "definition_id": "DEFEND_IRONCLAD",
                "name": "Defend",
                "current_cost": 1,
                "description": "Gain 5 Block.",
            },
        }
    ]
    snapshot["bound_actions"].update(
        {
            "actions": [
                {
                    "bound_action_id": "bound-play",
                    "verb": "play",
                    "subject_referent_id": "card-1",
                    "arguments": [],
                    "label": "Play Defend",
                },
                {
                    "bound_action_id": "bound-end",
                    "verb": "end_turn",
                    "subject_referent_id": None,
                    "arguments": [],
                    "label": "End Turn",
                },
            ],
            "materialized_count": 2,
            "total_count": 2,
        }
    )
    snapshot["reads"] = [
        {"read_id": "read-deck", "kind": "run_deck", "snapshot_bound": True},
        {"read_id": "read-piles", "kind": "combat_piles", "snapshot_bound": True},
    ]
    return snapshot


def _game_over_snapshot() -> dict[str, Any]:
    return _base_snapshot("game-over-2", 2, "game_over")


class _ScriptedEnvironment:
    ready: Mapping[str, Any] = _ready()

    def __init__(self, *, unknown_navigation: bool = False) -> None:
        self.current = _map_snapshot()
        self.unknown_navigation = unknown_navigation
        self.step_calls = 0

    def reset(self, seed: str) -> Mapping[str, Any]:
        self.current = _map_snapshot()
        return self.current

    def observe(self) -> Mapping[str, Any]:
        return self.current

    def read(self, read_id: str, snapshot_id: str) -> Mapping[str, Any]:
        return {
            "read_id": read_id,
            "snapshot_id": snapshot_id,
            "content": {"cards": [{"name": "Strike"}]},
            "completeness": {"status": "complete"},
        }

    def step(
        self,
        bound_action_id: str,
        snapshot_id: str,
        mutation_request_id: str | None = None,
    ) -> Mapping[str, Any]:
        self.step_calls += 1
        if self.current["interaction"]["kind"] == "map_navigation":
            if self.unknown_navigation:
                return {"delivery": "unknown", "request_id": mutation_request_id}
            self.current = _combat_snapshot()
        else:
            self.current = _game_over_snapshot()
        return {
            "delivery": "delivered",
            "reason_code": None,
            "request_id": mutation_request_id,
            "action": {"bound_action_id": bound_action_id},
            "successor": self.current,
        }

    def close(self) -> None:
        return None


def test_collects_real_port_shape_through_navigation_and_combat_successor() -> None:
    environment = _ScriptedEnvironment()

    collection = collect_managed_runtime(
        environment,
        seed="STPDFIXTURE00001",
        episode_id="episode-fixture",
        max_environment_actions=4,
        max_transitions=1,
    )

    assert collection.environment.host_kind == "managed_exact"
    assert collection.environment_actions == 2
    assert collection.termination_reason == "transition_limit"
    assert collection.family_counts == {"turn_action": 1}
    assert len(collection.raw_records) == 1
    assert len(collection.token_profile_records) == 6
    assert collection.transitions[0].terminal is True
    assert collection.transitions[0].eligibility.rank is False
    assert collection.transitions[0].policy.source == "deterministic_environment_probe"


def test_declared_behavior_fixture_can_be_rank_eligible_without_teacher_claim() -> None:
    collection = collect_managed_runtime(
        _ScriptedEnvironment(),
        seed="STPDFIXTURE00001",
        episode_id="episode-fixture",
        max_environment_actions=4,
        max_transitions=1,
        ranking_supervision="canonical-semantic-first",
    )

    transition = collection.transitions[0]
    assert transition.eligibility.rank is True
    assert transition.eligibility.rank_mode == "full_listwise"
    assert transition.policy.source == "deterministic_behavior_fixture"
    assert transition.policy.teacher_confidence is None


def test_unknown_navigation_delivery_is_not_retried() -> None:
    environment = _ScriptedEnvironment(unknown_navigation=True)

    with pytest.raises(ContractError, match="must not retry"):
        collect_managed_runtime(
            environment,
            seed="STPDFIXTURE00001",
            episode_id="episode-fixture",
            max_environment_actions=4,
            max_transitions=1,
        )

    assert environment.step_calls == 1
