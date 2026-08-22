from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from stpd.canonical import CanonicalizationError, canonical_json
from stpd.contracts import ContractError, EnvironmentIdentity, TransitionEligibility
from stpd.representation import (
    DecisionFamily,
    ExecutionEnvelope,
    InputProfile,
    ModelSerializerV0,
    PolicyProvenance,
    ResearchAction,
    ResearchState,
    ResearchTransition,
    ensure_action_catalog_alignment,
)

ROOT = Path(__file__).resolve().parents[1]


def _state(energy: int = 3) -> ResearchState:
    return ResearchState(
        information_policy_id="player_visible_v1",
        game_version="v0.111.0",
        game_commit="41cef1ea",
        decision_mode="combat",
        decision_family=DecisionFamily.TURN_ACTION,
        surface="combat_turn",
        facts={
            "combat": {"energy": energy},
            "card_details": {"K0": {"name": "Defend", "description": "Gain 5 Block."}},
            "hand": [{"local_ref": "H0", "detail_ref": "K0", "current_cost": 1}],
        },
        reads={"combat_piles": {"cards": [{"name": "Strike"}, {"name": "Defend"}]}},
    )


def _action() -> ResearchAction:
    return ResearchAction(
        action_key="play:defend:H0",
        kind="play_card",
        subject={"local_ref": "H0", "name": "Defend"},
        visible_cost=1,
        visible_effect="Gain 5 Block.",
    )


def test_research_state_hash_and_serialization_are_deterministic() -> None:
    state = _state()
    assert state.state_hash == _state().state_hash
    for profile in InputProfile:
        serializer = ModelSerializerV0(profile)
        assert serializer.serialize_state(state) == serializer.serialize_state(_state())
    lite = ModelSerializerV0(InputProfile.LITE).serialize_state(state)
    standard = ModelSerializerV0(InputProfile.STANDARD).serialize_state(state)
    full = ModelSerializerV0(InputProfile.FULL).serialize_state(state)
    assert "CARD_DETAILS" not in lite
    assert "card_details" in standard.lower()
    assert '"cards_count":2' in standard
    assert '"cards":[{"name":"Strike"}' in full


def test_model_action_is_semantic_and_excludes_execution_authority() -> None:
    rendered = ModelSerializerV0().serialize_action(_action())
    assert "play_card" in rendered and "Defend" in rendered
    assert "bound_action_id" not in rendered and "snapshot_id" not in rendered


def test_model_input_leakage_fails_closed() -> None:
    state = _state()
    poisoned = ResearchState(
        state.information_policy_id,
        state.game_version,
        state.game_commit,
        state.decision_mode,
        state.decision_family,
        state.surface,
        {"combat": {"hidden_rng": 17}},
    )
    with pytest.raises(CanonicalizationError, match="hidden_rng"):
        poisoned.validate()


def test_execution_mapping_is_bijective() -> None:
    action = _action()
    envelope = ExecutionEnvelope(action.action_key, "snapshot-1", "bound-1", "request-1")
    ensure_action_catalog_alignment([action], [envelope])
    with pytest.raises(ContractError, match="not bijective"):
        ensure_action_catalog_alignment([action], [])


def test_transition_requires_stable_successor_and_current_chosen_action() -> None:
    action = _action()
    transition = ResearchTransition(
        transition_id="t1",
        episode_id="e1",
        step_index=0,
        seed="STPDFIXTURE00001",
        environment=EnvironmentIdentity(
            "v0.111.0",
            "41cef1ea",
            "managed_exact",
            "host-source",
            "a" * 64,
            "v1.1.0-rc.1",
            "connector-source",
            "b" * 64,
            "1.0.0",
            "player_visible_v1",
        ),
        policy=PolicyProvenance("fixture", "1", "config", None),
        decision_mode="combat",
        surface="combat_turn",
        input_profile=InputProfile.STANDARD,
        eligibility=TransitionEligibility(True, "full_listwise", True, False, "complete"),
        state=_state(),
        legal_actions=(action,),
        chosen_action=action,
        successor=None,
        terminal=False,
        scope_exit=False,
        outcome=None,
        raw_ref="raw/e1#0",
    )
    with pytest.raises(ContractError, match="stable successor"):
        transition.validate()


def test_golden_transition_validates_against_all_three_schemas() -> None:
    schemas = {}
    for name in ("research-state-v0", "research-action-v0", "research-transition-v0"):
        schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
        schemas[schema["$id"]] = schema
    registry = Registry().with_resources(
        (uri, Resource.from_contents(schema)) for uri, schema in schemas.items()
    )
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "research-transition-v0.golden.json").read_text()
    )
    validator = Draft202012Validator(
        schemas[next(k for k in schemas if "transition" in k)], registry=registry
    )
    validator.validate(fixture)
    assert canonical_json(fixture) == canonical_json(json.loads(canonical_json(fixture)))
