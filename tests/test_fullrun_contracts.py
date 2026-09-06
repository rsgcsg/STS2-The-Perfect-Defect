from __future__ import annotations

from dataclasses import replace

import pytest

from stpd.fullrun.contracts import ResearchTransitionV1, SemanticState
from stpd.fullrun.fixtures import SyntheticSourceAdapter, synthetic_bundle
from stpd.fullrun.representation import FullRunSerializer, decision_fingerprint
from stpd.json_boundary import BoundaryError, FrozenObject, decode_json, json_bytes


def transition() -> ResearchTransitionV1:
    return SyntheticSourceAdapter().project(synthetic_bundle(runs=3)).transitions[0]


def test_fullrun_roundtrip_and_noncombat_continuity() -> None:
    projection = SyntheticSourceAdapter().project(synthetic_bundle(runs=3))
    assert len(projection.transitions) == 36
    assert len({r.surface for r in projection.transitions}) == 12
    assert projection.scope == "engineering"
    for record in projection.transitions:
        assert ResearchTransitionV1.decode(record.to_dict()) == record
        assert record.rank_eligible
        assert record.provenance.scope == "engineering"
    assert not projection.transitions[1].terminal


def test_candidate_permutation_preserves_text_and_input_fingerprint() -> None:
    record = transition()
    permuted = replace(record, actions=tuple(reversed(record.actions)))
    serializer = FullRunSerializer()
    state, actions = serializer.serialize(record)
    changed_state, changed_actions = serializer.serialize(permuted)
    assert state == changed_state
    assert actions == tuple(reversed(changed_actions))
    assert decision_fingerprint(record) == decision_fingerprint(permuted)
    assert all(action.key not in actions[index] for index, action in enumerate(record.actions))


def test_provenance_and_future_successor_never_enter_input() -> None:
    record = transition()
    changed = replace(record, run_id="different-run", successor=SemanticState(
        FrozenObject.of({"future_outcome": "win"}), FrozenObject()))
    serializer = FullRunSerializer()
    assert serializer.serialize(record) == serializer.serialize(changed)
    assert record.provenance.native_root_ref not in serializer.serialize_state(record.state)


@pytest.mark.parametrize("field", ["runtime_instance_id", "nativeObjectID", "timestamp",
                                   "chosen_key", "candidate_position", "run_outcome", "successor"])
def test_leakage_is_rejected(field: str) -> None:
    record = transition()
    state = replace(record.state, decision=FrozenObject.of({field: "forbidden"}))
    with pytest.raises(BoundaryError, match="forbidden"):
        FullRunSerializer().serialize_state(state)


def test_public_observation_and_actions_are_not_reinterpreted() -> None:
    record = transition().to_dict()
    record["state"]["boundary"] = "human_observation"
    with pytest.raises(BoundaryError, match="human_observation"):
        ResearchTransitionV1.decode(record)
    record = transition().to_dict()
    record["catalog_source"] = "public_bound_actions"
    with pytest.raises(BoundaryError, match="public_actions"):
        ResearchTransitionV1.decode(record)


def test_missing_native_evidence_duplicate_and_unknown_schema_fail() -> None:
    record = transition()
    with pytest.raises(BoundaryError, match="commit"):
        replace(record, provenance=replace(record.provenance, commit_ref=None))
    with pytest.raises(BoundaryError, match="successor"):
        replace(record, successor=None, terminal=False)
    with pytest.raises(BoundaryError, match="duplicate_candidate"):
        replace(record, actions=(record.actions[0], record.actions[0]))
    value = record.to_dict()
    value["schema"] = "future"
    with pytest.raises(BoundaryError, match="unsupported_schema"):
        ResearchTransitionV1.decode(value)


def test_source_adapter_rejects_incomplete_run_and_final_schema_guessing() -> None:
    value = decode_json(synthetic_bundle(runs=3))
    value["records"].pop()
    with pytest.raises(BoundaryError, match="disposition"):
        SyntheticSourceAdapter().project(json_bytes(value))
    value = decode_json(synthetic_bundle(runs=3))
    value["schema"] = "sts2/platform-final-not-known"
    with pytest.raises(BoundaryError, match="not_installed"):
        SyntheticSourceAdapter().project(json_bytes(value))


def test_profiles_are_provisional_and_reads_have_explicit_admission() -> None:
    state = transition().state
    lite = FullRunSerializer("lite")
    standard = FullRunSerializer("standard")
    assert lite.identity["status"] == standard.identity["status"] == "provisional"
    assert lite.state_content(state)["READS"] == []
    assert len(standard.state_content(state)["READS"]) == 1
    assert "evidence_ref" not in standard.serialize_state(state)
