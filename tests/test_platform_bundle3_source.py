from __future__ import annotations

import io
import tarfile
from dataclasses import replace
from pathlib import Path

import pytest
from platform_bundle3_fixture import bundle3, load, rows, seal, stream, write

from stpd.fullrun.contracts import ResearchTransitionV1, ResearchTransitionV2
from stpd.fullrun.data import admit, load_dataset, publish_dataset, publish_source
from stpd.fullrun.platform_bundle3 import PlatformBundle3SourceAdapter, archive_bundle
from stpd.fullrun.representation import FullRunSerializer
from stpd.json_boundary import BoundaryError


def test_verified_bundle3_parent_read_and_strict_dataset_roundtrip(tmp_path: Path) -> None:
    from test_artifact_store_v1 import PRODUCER, store

    bundle = bundle3(tmp_path)
    adapter = PlatformBundle3SourceAdapter()
    raw = archive_bundle(bundle)
    assert raw == archive_bundle(bundle)
    target = store(tmp_path / "store")
    source, projection = publish_source(target, raw, adapter, PRODUCER)
    assert projection.scope == "platform_verified"  # No Human/scientific qualification flag.
    assert len(projection.transitions) == 6
    parent, child = projection.transitions[:2]
    assert isinstance(parent, ResearchTransitionV2) and isinstance(child, ResearchTransitionV2)
    assert (
        child.occurrence.value()["parent_decision_id"] == parent.occurrence.value()["decision_id"]
    )
    assert child.provenance.native_root_ref == parent.provenance.native_root_ref
    assert child.action_space_authority == "public_bound_actions"
    assert {read.kind for read in child.state.reads} == {"run_deck", "combat_piles"}
    assert ResearchTransitionV1.decode(child.to_dict()) == child
    rendered = str(FullRunSerializer().serialize(child))
    assert "card-1" not in rendered and "Strike" in rendered
    assert "snapshot-" not in rendered and "decision-" not in rendered
    dataset = admit((projection,))
    published = publish_dataset(target, dataset, (source,), PRODUCER)
    _, reloaded = load_dataset(target, published.artifact_id)
    assert reloaded == dataset
    assert source.parameters.value()["accounting"] == projection.accounting.value()


def test_changed_projected_choice_cannot_bypass_source_reprojection(tmp_path: Path) -> None:
    projection = PlatformBundle3SourceAdapter().project(archive_bundle(bundle3(tmp_path)))
    altered = replace(projection.transitions[0], family="forged")
    with pytest.raises(BoundaryError, match="source_transition_projection_mismatch"):
        admit((replace(projection, transitions=(altered, *projection.transitions[1:])),))
    with pytest.raises(BoundaryError, match="unverified_platform_projection"):
        admit((replace(projection, source_bytes=None),))


def test_resealed_parent_tamper_is_rejected_by_owner_verifier(tmp_path: Path) -> None:
    bundle = bundle3(tmp_path)
    raw = bundle / "raw"
    for name in ("canonical-transitions.jsonl", "semantic-boundary-trace.jsonl"):
        values = rows(raw / name)
        for value in values:
            decision = value["action"]["decision"] if "kind" in value else value["decision"]
            if decision["decision_kind"] == "nested_selector":
                decision["parent_decision_id"] = "missing"
        stream(raw / name, values)
    seal(bundle)
    with pytest.raises(BoundaryError, match="bundle3_verification_failed"):
        PlatformBundle3SourceAdapter().project(archive_bundle(bundle))


def test_two_real_components_are_not_promoted_to_three(tmp_path: Path) -> None:
    projection = PlatformBundle3SourceAdapter().project(archive_bundle(bundle3(tmp_path, runs=2)))
    with pytest.raises(BoundaryError, match="insufficient_independent_run_components"):
        admit((projection,))


def test_missing_native_start_does_not_become_complete_run(tmp_path: Path) -> None:
    bundle = bundle3(tmp_path)
    path = bundle / "raw/run-journal.jsonl"
    values = rows(path)
    values[1]["kind"] = "run_observed_in_progress"
    stream(path, values)
    seal(bundle)
    projection = PlatformBundle3SourceAdapter().project(archive_bundle(bundle))
    assert len(projection.run_proofs.value()) == 2
    with pytest.raises(BoundaryError, match="run_proof_inventory_mismatch"):
        admit((projection,))


def test_real_failure_preserved_and_rejected_but_diagnostic_not_failure(tmp_path: Path) -> None:
    bundle = bundle3(tmp_path)
    raw = bundle / "raw"
    manifest = load(raw / "recording-manifest.json")
    invalidation = {
        "schema_version": 2,
        "schema": "sts2.human-annotator/invalidation-2",
        "session_id": manifest["session_id"],
        "run_id": "run-0001",
        "disposition": "diagnostic",
        "reason_code": "synthetic_diagnostic",
    }
    stream(raw / "invalidations.jsonl", [invalidation])
    audit = load(bundle / "audit/audit-report.json")
    audit["invalidations"] = 1
    write(bundle / "audit/audit-report.json", audit)
    seal(bundle)
    adapter = PlatformBundle3SourceAdapter()
    projection = adapter.project(archive_bundle(bundle))
    assert len(admit((projection,)).records) == 6
    invalidation.update(
        disposition="failed_closed",
        decision_failure={
            "kind": "capture",
            "action_family": "ordinary_combat.play_card",
            "decision_witness_id": "capture-missed",
        },
        human_occurrence={
            "occurrence_id": "capture-missed",
            "native_action_type": "Fixture",
            "family": "ordinary_combat.play_card",
            "verb": "play",
            "native_mechanism": "fixture",
            "native_operands": {},
            "disposition": "failed_closed",
        },
    )
    stream(raw / "invalidations.jsonl", [invalidation])
    seal(bundle)
    projection = adapter.project(archive_bundle(bundle))
    assert projection.accounting.value()["invalidations"][0]["disposition"] == "failed_closed"
    with pytest.raises(BoundaryError, match="failed_closed_human_decision"):
        admit((projection,))


@pytest.mark.parametrize("name", ["../escape", "/absolute", "x\\y", "x/../y", "C:/escape"])
def test_archive_traversal_is_rejected(tmp_path: Path, name: str) -> None:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as archive:
        info = tarfile.TarInfo(name)
        info.size = 2
        archive.addfile(info, io.BytesIO(b"{}"))
    with pytest.raises(BoundaryError, match="unsafe_or_duplicate_member"):
        PlatformBundle3SourceAdapter().project(raw.getvalue())
    assert not (tmp_path / "escape").exists()


def test_archive_symlink_is_rejected() -> None:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as archive:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        archive.addfile(info)
    with pytest.raises(BoundaryError, match="unsafe_or_duplicate_member"):
        PlatformBundle3SourceAdapter().project(raw.getvalue())


def test_native_execution_catalog_stays_distinct_from_public_catalog(tmp_path: Path) -> None:
    import hashlib

    from stpd.json_boundary import json_bytes

    bundle = bundle3(tmp_path)
    raw = bundle / "raw"
    canonical = rows(raw / "canonical-transitions.jsonl")
    trace = rows(raw / "semantic-boundary-trace.jsonl")
    first = canonical[0]
    space = {
        "schema_version": 3,
        "schema": "sts2.human-annotator/execution-semantic-action-space-3",
        "action_witness_id": first["action_witness_id"],
        "semantic_state_digest": "a" * 64,
        "semantic_catalog_digest": "b" * 64,
        "phase": "before_execution",
        "status": "captured",
        "observed_membership": "exact_once",
        "observed_match_count": 1,
        "observed_action_key": "native-select",
        "human_bound_action_id": first["action"]["bound_action_id"],
        "semantic_state": {"player": {"hp": 40, "energy": 2}},
        "actions": [
            {
                "key": "native-select",
                "verb": "select",
                "subject_referent_id": "card-1",
                "arguments": {},
            }
        ],
    }
    content = json_bytes(space)
    sha = hashlib.sha256(content).hexdigest()
    path = f"semantic-action-spaces/sha256/{sha[:2]}/{sha}.json"
    (raw / path).parent.mkdir(parents=True, exist_ok=True)
    (raw / path).write_bytes(content)
    ref = {
        "object_ref": path,
        "content_sha256": sha,
        **{
            key: space[key]
            for key in ("action_witness_id", "semantic_state_digest", "semantic_catalog_digest")
        },
    }
    first.update(
        action_space_authority="native_semantic_execution",
        execution_semantic_action_space_ref=ref,
        native_mechanism="game_action",
    )
    for event in trace:
        if event["action"]["action_witness_id"] == first["action_witness_id"]:
            event["action"].update(native_mechanism="game_action", native_queue_id=1)
            if event["kind"] == "transition_proved":
                event["execution_semantic_action_space_ref"] = ref
                event["native_completion"] = {
                    "action_witness_id": first["action_witness_id"],
                    "succeeded": True,
                    "kind": "fixture_native_commit",
                }
    stream(raw / "canonical-transitions.jsonl", canonical)
    stream(raw / "semantic-boundary-trace.jsonl", trace)
    seal(bundle)
    projection = PlatformBundle3SourceAdapter().project(archive_bundle(bundle))
    first_record, child = projection.transitions[:2]
    assert isinstance(first_record, ResearchTransitionV2)
    assert isinstance(child, ResearchTransitionV2)
    assert first_record.action_space_authority == "native_semantic_execution"
    assert first_record.chosen_key == "native-select"
    assert first_record.state.decision.value()["execution"]["player"]["energy"] == 2
    assert child.action_space_authority == "public_bound_actions"
    assert len(admit((projection,)).records) == 6


def test_unknown_disposition_survives_source_but_blocks_dataset(tmp_path: Path) -> None:
    bundle = bundle3(tmp_path)
    raw = bundle / "raw"
    canonical = rows(raw / "canonical-transitions.jsonl")
    last = canonical.pop()
    trace = rows(raw / "semantic-boundary-trace.jsonl")
    trace[-1] = {
        key: value
        for key, value in trace[-1].items()
        if key not in {"execution_pre_ref", "successor_ref"}
    }
    trace[-1]["kind"] = "transition_unknown"
    stream(raw / "canonical-transitions.jsonl", canonical)
    stream(raw / "semantic-boundary-trace.jsonl", trace)
    for path in (bundle / "session-bundle-manifest.json", bundle / "audit/audit-report.json"):
        value = load(path)
        value["canonical_count"] = len(canonical)
        write(path, value)
    seal(bundle)
    projection = PlatformBundle3SourceAdapter().project(archive_bundle(bundle))
    assert projection.accounting.value()["counts"]["transition_unknown"] == 1
    assert any(
        item["action"]["action_witness_id"] == last["action_witness_id"]
        for item in projection.accounting.value()["occurrences"]
    )
    with pytest.raises(BoundaryError, match="unresolved_or_unpersisted_occurrence"):
        admit((projection,))


def test_unordered_pile_cards_and_runtime_ids_do_not_enter_model_order() -> None:
    from stpd.fullrun.platform_bundle3 import _SemanticProjection

    left = {
        "kind": "run_deck",
        "cards": [
            {"entity_id": "volatile-b", "name": "B"},
            {"entity_id": "volatile-a", "name": "A"},
        ],
    }
    right = {
        "kind": "run_deck",
        "cards": [{"entity_id": "new-a", "name": "A"}, {"entity_id": "new-b", "name": "B"}],
    }
    assert _SemanticProjection([left]).clean(left) == _SemanticProjection([right]).clean(right)
