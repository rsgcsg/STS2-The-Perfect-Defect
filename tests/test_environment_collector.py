from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import pytest

from stpd.contracts import ContractError, EnvironmentIdentity
from stpd.environment import CollectionError, ResearchProjectorV0, StableTransitionCollector
from stpd.representation import InputProfile, PolicyProvenance


def _snapshot(snapshot_id: str, *, energy: int = 3) -> dict:
    return {
        "protocol_version": "1.0.0",
        "schema": "sts2.player-environment/snapshot-1",
        "snapshot_id": snapshot_id,
        "sequence": 1,
        "observed_at": "2026-08-22T00:00:00Z",
        "status": "interactive",
        "persistent": {"content": {"player": {"hp": 80}, "run": {"floor": 1}}},
        "interaction": {
            "interaction_id": f"interaction-{snapshot_id}",
            "kind": "combat_turn",
            "stage": "turn",
            "content_schema": "sts2.player-environment/surface/combat_turn-1",
            "content": {
                "surface": {"kind": "combat_turn"},
                "context": {"kind": "combat"},
                "energy": energy,
            },
            "capabilities": [],
        },
        "referents": [
            {
                "referent_id": "runtime-card-1",
                "role": "hand_card",
                "kind": "entity",
                "label": "Defend",
                "state": {
                    "visible": True,
                    "enabled": True,
                    "observation_basis": "native_visible_fact",
                },
                "properties": {
                    "entity_id": "native-object-17",
                    "definition_id": "DEFEND_IRONCLAD",
                    "name": "Defend",
                    "current_cost": 1,
                    "description": "Gain 5 Block.",
                },
            }
        ],
        "bound_actions": {
            "schema": "sts2.player-environment/bound-actions-1",
            "status": "complete",
            "materialized_count": 2,
            "total_count": 2,
            "limit": 512,
            "ordering_semantics": "fixture",
            "actions": [
                {
                    "bound_action_id": f"bound-play-{snapshot_id}",
                    "verb": "play",
                    "interaction_id": f"interaction-{snapshot_id}",
                    "subject_referent_id": "runtime-card-1",
                    "arguments": [],
                    "label": "Play Defend",
                },
                {
                    "bound_action_id": f"bound-end-{snapshot_id}",
                    "verb": "end_turn",
                    "interaction_id": f"interaction-{snapshot_id}",
                    "subject_referent_id": None,
                    "arguments": [],
                    "label": "End Turn",
                },
            ],
        },
        "reads": [
            {
                "read_id": f"read-piles-{snapshot_id}",
                "kind": "combat_piles",
                "content_schema": "sts2.player-environment/read/combat_piles-1",
                "snapshot_bound": True,
            }
        ],
        "completeness": {
            "status": "complete",
            "visible_information": "fixture complete",
            "interaction_discovery": "fixture",
            "missing": [],
            "hidden_by_policy": ["draw_pile_true_order"],
        },
        "session": {
            "runtime_instance_id": "runtime-secret",
            "environment_fingerprint": "environment-secret",
        },
        "information_policy": {
            "id": "player_visible_v1",
            "scope": "player visible",
            "includes_hidden_information": False,
            "unknown_field_behavior": "omit_and_mark_incomplete",
        },
    }


class _Environment:
    ready: Mapping[str, Any] = {"type": "ready"}

    def __init__(self, successor: dict, *, delivery: str = "delivered") -> None:
        self.successor = successor
        self.delivery = delivery
        self.steps = 0
        self.reads = 0

    def reset(self, seed):
        return _snapshot("s0")

    def observe(self):
        return self.successor

    def read(self, read_id, snapshot_id):
        self.reads += 1
        return {
            "kind": "combat_piles",
            "content": {"zones": [{"zone": "draw", "cards": [{"name": "Strike"}]}]},
            "completeness": {"status": "complete"},
            "snapshot_id": snapshot_id,
            "read_id": read_id,
        }

    def step(self, bound_action_id, snapshot_id, mutation_request_id=None):
        self.steps += 1
        return {
            "delivery": self.delivery,
            "reason_code": None,
            "request_id": mutation_request_id,
            "action": {"bound_action_id": bound_action_id},
            "successor": self.successor,
        }

    def close(self):
        return None


def _collector(environment: _Environment) -> StableTransitionCollector:
    return StableTransitionCollector(
        environment,
        ResearchProjectorV0(),
        environment_identity=EnvironmentIdentity(
            "v0.111.0",
            "41cef1ea",
            "c" * 64,
            "11111111-1111-4111-8111-111111111111",
            "managed_exact",
            "headless-source",
            "d" * 64,
            "a" * 64,
            "22222222-2222-4222-8222-222222222222",
            "1.0.0",
            "sts2_headless_managed_adapter",
            "headless-source",
            "d" * 64,
            "player_visible_v1",
        ),
        policy=PolicyProvenance("fixture_teacher", "1", "config", None),
        input_profile=InputProfile.STANDARD,
        read_kinds=("combat_piles",),
    )


def test_projector_separates_semantics_from_execution_authority() -> None:
    projected = ResearchProjectorV0().project(
        _snapshot("s0"),
        {},
        game_version="v0.111.0",
        game_commit="41cef1ea",
        mutation_request_prefix="t1",
    )
    rendered = str(projected.state.to_dict()) + str([item.to_dict() for item in projected.actions])
    assert "runtime-card-1" not in rendered
    assert "native-object-17" not in rendered
    assert "bound-play-s0" not in rendered
    assert projected.actions[0].subject is not None
    assert projected.actions[0].subject["local_ref"] == "H0"
    assert projected.envelopes[0].bound_action_id == "bound-play-s0"


def test_projector_action_keys_do_not_depend_on_catalog_order() -> None:
    forward = _snapshot("s0")
    reversed_snapshot = copy.deepcopy(forward)
    reversed_snapshot["bound_actions"]["actions"].reverse()
    projector = ResearchProjectorV0()
    first = projector.project(
        forward,
        {},
        game_version="v0.111.0",
        game_commit="41cef1ea",
        mutation_request_prefix="first",
    )
    second = projector.project(
        reversed_snapshot,
        {},
        game_version="v0.111.0",
        game_commit="41cef1ea",
        mutation_request_prefix="second",
    )
    assert {action.action_key for action in first.actions} == {
        action.action_key for action in second.actions
    }


def test_projector_rejects_noncombat_selection_even_when_surface_name_matches() -> None:
    snapshot = _snapshot("s0")
    snapshot["interaction"]["kind"] = "card_reward_selection"
    snapshot["interaction"]["content"]["context"]["kind"] = "reward"
    with pytest.raises(ContractError, match="Combat semantic context"):
        ResearchProjectorV0().project(
            snapshot,
            {},
            game_version="v0.111.0",
            game_commit="41cef1ea",
            mutation_request_prefix="reward",
        )


def test_state_only_projection_does_not_admit_unsupported_next_actions() -> None:
    snapshot = _snapshot("s0")
    snapshot["interaction"]["kind"] = "card_choice"
    snapshot["referents"][0]["role"] = "card_choice"
    snapshot["bound_actions"]["actions"] = [
        {
            "bound_action_id": "bound-select-s0",
            "verb": "select",
            "interaction_id": "interaction-s0",
            "subject_referent_id": "runtime-card-1",
            "arguments": [],
            "label": "Select Defend",
        }
    ]
    snapshot["bound_actions"]["materialized_count"] = 1
    snapshot["bound_actions"]["total_count"] = 1
    projector = ResearchProjectorV0()

    state = projector.project_state(
        snapshot,
        {},
        game_version="v0.111.0",
        game_commit="41cef1ea",
    )

    assert state.decision_family.value == "card_choice"
    with pytest.raises(ContractError, match="unsupported v0 action"):
        projector.project(
            snapshot,
            {},
            game_version="v0.111.0",
            game_commit="41cef1ea",
            mutation_request_prefix="unsupported",
        )


def test_collector_emits_stable_transition_with_reads_and_exact_receipt() -> None:
    environment = _Environment(_snapshot("s1", energy=2))
    result = _collector(environment).collect_one(
        _snapshot("s0"),
        choose=lambda projected: projected.actions[0].action_key,
        transition_id="transition-1",
        episode_id="episode-1",
        step_index=0,
        seed="STPDFIXTURE00001",
        raw_ref="raw/fixture#0",
        rank_eligible=True,
    )
    assert result.transition.successor is not None
    assert (
        result.transition.state.reads["combat_piles"]["zones"][0]["cards"][0]["name"]
        == "Strike"
    )
    assert result.successor["snapshot_id"] == "s1"
    assert result.receipt["delivery"] == "delivered"
    assert environment.steps == 1 and environment.reads == 2


def test_unknown_delivery_is_not_retried() -> None:
    environment = _Environment(_snapshot("s1"), delivery="unknown")
    with pytest.raises(CollectionError, match="must not retry"):
        _collector(environment).collect_one(
            _snapshot("s0"),
            choose=lambda projected: projected.actions[0].action_key,
            transition_id="transition-1",
            episode_id="episode-1",
            step_index=0,
            seed="STPDFIXTURE00001",
            raw_ref="raw/fixture#0",
            rank_eligible=False,
        )
    assert environment.steps == 1


def test_partial_snapshot_and_unadvertised_policy_choice_fail_before_execution() -> None:
    environment = _Environment(_snapshot("s1"))
    partial = copy.deepcopy(_snapshot("s0"))
    partial["completeness"]["status"] = "partial"
    with pytest.raises(ContractError, match="completeness"):
        _collector(environment).collect_one(
            partial,
            choose=lambda _projected: "outside",
            transition_id="transition-1",
            episode_id="episode-1",
            step_index=0,
            seed="STPDFIXTURE00001",
            raw_ref="raw/fixture#0",
            rank_eligible=False,
        )
    assert environment.steps == 0

    with pytest.raises(CollectionError, match="outside"):
        _collector(environment).collect_one(
            _snapshot("s0"),
            choose=lambda _projected: "outside",
            transition_id="transition-2",
            episode_id="episode-1",
            step_index=1,
            seed="STPDFIXTURE00001",
            raw_ref="raw/fixture#1",
            rank_eligible=False,
        )
    assert environment.steps == 0


def test_runtime_identity_drift_quarantines_delivered_transition() -> None:
    successor = _snapshot("s1")
    successor["session"]["runtime_instance_id"] = "new-runtime"
    environment = _Environment(successor)
    with pytest.raises(CollectionError, match="runtime identity changed"):
        _collector(environment).collect_one(
            _snapshot("s0"),
            choose=lambda projected: projected.actions[0].action_key,
            transition_id="transition-drift",
            episode_id="episode-1",
            step_index=0,
            seed="STPDFIXTURE00001",
            raw_ref="raw/fixture#drift",
            rank_eligible=False,
        )
    assert environment.steps == 1
