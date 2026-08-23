from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from stpd.data.b0 import validate_b0
from stpd.data.human_annotator import HumanRecordRejection, import_human_recording
from stpd.data.manifest import DataSource
from stpd.data.pipeline import build_canonical_dataset


def test_data_package_preserves_existing_and_human_exports() -> None:
    import stpd.data as data

    assert "build_canonical_dataset" in data.__all__
    assert "write_transition_parquet" in data.__all__
    assert "import_human_recording" in data.__all__


def _snapshot(snapshot_id: str, *, interaction_id: str = "interaction-1") -> dict[str, Any]:
    return {
        "protocol_version": "1.0.0",
        "schema": "sts2.player-environment/snapshot-1",
        "snapshot_id": snapshot_id,
        "sequence": 1,
        "observed_at": "2026-08-23T00:00:00Z",
        "status": "interactive",
        "persistent": {"kind": "run", "hp": 50},
        "interaction": {
            "interaction_id": interaction_id,
            "kind": "combat_turn",
            "stage": "choosing",
            "prompt": None,
            "content_schema": "sts2.player-environment/surface/combat-turn-1",
            "content": {
                "surface": {"kind": "combat_turn"},
                "context": {"kind": "combat"},
            },
            "capabilities": [],
        },
        "referents": [
            {
                "referent_id": "card-1",
                "role": "hand_card",
                "kind": "card",
                "label": "Strike",
                "state": {
                    "visible": True,
                    "enabled": True,
                    "selected": False,
                    "focused": False,
                    "observation_basis": "native_ui",
                },
                "properties_schema": "card-1",
                "properties": {"name": "Strike", "current_cost": 1},
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
                    "bound_action_id": "bound-play",
                    "verb": "play",
                    "interaction_id": interaction_id,
                    "subject_referent_id": "card-1",
                    "arguments": [],
                    "label": "Play Strike",
                },
                {
                    "bound_action_id": "bound-end",
                    "verb": "end_turn",
                    "interaction_id": interaction_id,
                    "subject_referent_id": None,
                    "arguments": [],
                    "label": "End turn",
                },
            ],
        },
        "reads": [],
        "completeness": {
            "status": "complete",
            "visible_information": "complete",
            "interaction_discovery": "complete",
            "missing": [],
            "hidden_by_policy": [],
        },
        "session": {
            "runtime_instance_id": "runtime-1",
            "environment_fingerprint": "environment-1",
        },
        "information_policy": {
            "id": "player_visible_v1",
            "scope": "fair_player",
            "includes_hidden_information": False,
            "unknown_field_behavior": "omit",
        },
    }


def _record() -> dict[str, Any]:
    sha = "a" * 64
    revision = "b" * 40
    mvid = "00000000-0000-0000-0000-000000000001"
    artifact = {
        "product": "artifact",
        "version": "0.1.0",
        "source_revision": revision,
        "source_digest_sha256": sha,
        "sha256": sha,
        "module_version_id": mvid,
    }
    pre = _snapshot("snapshot-a")
    successor = _snapshot("snapshot-b", interaction_id="interaction-2")
    catalog_digest = hashlib.sha256(
        json.dumps(
            pre["bound_actions"],
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "schema": "sts2.human-annotator/decision-record-1",
        "record_id": "record-1",
        "session_id": "session-1",
        "run_id": "run-0001",
        "sequence": 1,
        "recorded_at": "2026-08-23T00:00:01Z",
        "environment": {
            "game": {
                "version": "v0.111.0",
                "commit": "41cef1ea",
                "main_assembly_sha256": sha,
                "main_assembly_module_version_id": mvid,
            },
            "connector": artifact,
            "annotator": artifact,
            "player_environment_protocol": "1.0.0",
            "runtime_instance_id": "runtime-1",
            "environment_fingerprint": "environment-1",
            "modset_status": "canary_exact_observer_modset",
            "modset_fingerprint": sha,
        },
        "pre": {
            "snapshot_id": "snapshot-a",
            "interaction_id": "interaction-1",
            "interaction_kind": "combat_turn",
            "surface_schema": "sts2.player-environment/surface/combat-turn-1",
            "catalog_digest": catalog_digest,
            "catalog_count": 2,
            "snapshot": pre,
        },
        "native_witness": {
            "origin": "native_card_play_ui",
            "native_action_type": "PlayCardAction",
            "subject_witness_id": "card-native-1",
            "argument_witness_ids": {},
            "accepted_at": "2026-08-23T00:00:00Z",
        },
        "mapping": {
            "status": "exact_unique",
            "match_count": 1,
            "basis": "reference_equality_to_frozen_host_binding",
            "detail": None,
        },
        "action": {
            "bound_action_id": "bound-play",
            "verb": "play",
            "subject_referent_id": "card-1",
            "arguments": {},
            "label": "Play Strike",
        },
        "successor": {
            "snapshot_id": "snapshot-b",
            "status": "interactive",
            "interaction_id": "interaction-2",
            "interaction_kind": "combat_turn",
            "observed_at": "2026-08-23T00:00:01Z",
            "snapshot": successor,
        },
        "decision_family": "ordinary_combat",
        "surface": "sts2.player-environment/surface/combat-turn-1",
        "eligibility": {"status": "admitted", "passed_gates": [], "non_claims": []},
    }


def _import(tmp_path: Path, record: dict[str, Any]):
    path = tmp_path / "human.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return import_human_recording(path)


def test_exact_human_record_projects_existing_stpd_contract(tmp_path: Path) -> None:
    report = _import(tmp_path, _record())

    assert report.accepted_count == 1
    assert report.rejected_count == 0
    transition = report.accepted[0].transition
    assert transition.policy.source == "human_native_ui"
    assert transition.eligibility.rank_mode == "full_listwise"
    assert transition.chosen_action in transition.legal_actions
    assert transition.successor is not None
    assert transition.episode_id == "human:session-1/run-0001"
    b0 = validate_b0(
        [transition.to_dict()], schema_root=Path(__file__).parents[1] / "schemas"
    )
    assert b0.verdict == "pass", b0.findings
    manifest, dataset_b0 = build_canonical_dataset(
        [transition.to_dict()],
        output_dir=tmp_path / "dataset",
        schema_root=Path(__file__).parents[1] / "schemas",
        source=DataSource(
            "human-fixture",
            "human_native_ui",
            report.source_sha256,
            "LicenseRef-Private-Human-Data",
            "fixture://human.jsonl",
        ),
        stpd_source_revision="c" * 40,
        created_at="2026-08-23T00:00:00Z",
        split_salt="human-fixture-v1",
    )
    assert dataset_b0.verdict == "pass"
    assert manifest.row_count == 1
    assert manifest.split["strategy"] == "seed_root_sha256_v0"


def test_unsupported_successor_actions_do_not_reject_a_supported_decision(
    tmp_path: Path,
) -> None:
    record = _record()
    successor = record["successor"]["snapshot"]
    successor["interaction"]["kind"] = "card_choice"
    successor["referents"][0]["role"] = "card_choice"
    successor["bound_actions"]["actions"] = [
        {
            "bound_action_id": "bound-select",
            "verb": "select",
            "interaction_id": "interaction-2",
            "subject_referent_id": "card-1",
            "arguments": [],
            "label": "Select Strike",
        }
    ]
    successor["bound_actions"]["materialized_count"] = 1
    successor["bound_actions"]["total_count"] = 1
    record["successor"]["interaction_kind"] = "card_choice"

    report = _import(tmp_path, record)

    assert report.accepted_count == 1
    assert report.rejected_count == 0
    assert report.accepted[0].transition.successor is not None
    assert report.accepted[0].transition.successor.decision_family.value == "card_choice"


def test_non_unique_mapping_is_rejected(tmp_path: Path) -> None:
    record = _record()
    record["mapping"] = {"status": "ambiguous", "match_count": 2, "basis": "x"}

    report = _import(tmp_path, record)

    assert report.accepted_count == 0
    assert report.rejected[0].reason is HumanRecordRejection.MAPPING_NOT_EXACT_UNIQUE


def test_action_not_in_frozen_catalog_is_rejected(tmp_path: Path) -> None:
    record = _record()
    record["action"]["bound_action_id"] = "invented"

    report = _import(tmp_path, record)

    assert report.accepted_count == 0
    assert report.rejected[0].reason is HumanRecordRejection.CHOSEN_ACTION_NOT_EXACTLY_ONCE


def test_runtime_drift_is_rejected(tmp_path: Path) -> None:
    record = _record()
    record["successor"]["snapshot"]["session"]["runtime_instance_id"] = "runtime-2"

    report = _import(tmp_path, record)

    assert report.accepted_count == 0
    assert report.rejected[0].reason is HumanRecordRejection.RUNTIME_IDENTITY_DRIFT


def test_inexact_artifact_identity_is_rejected(tmp_path: Path) -> None:
    record = copy.deepcopy(_record())
    record["environment"]["connector"]["source_digest_sha256"] = "missing"

    report = _import(tmp_path, record)

    assert report.accepted_count == 0
    assert report.rejected[0].reason is HumanRecordRejection.MISSING_EXACT_IDENTITY


def test_catalog_tampering_is_rejected(tmp_path: Path) -> None:
    record = _record()
    record["pre"]["snapshot"]["bound_actions"]["actions"][0]["verb"] = "invented"

    report = _import(tmp_path, record)

    assert report.accepted_count == 0
    assert report.rejected[0].reason is HumanRecordRejection.PRE_FRAME_NOT_AUTHORITATIVE


def test_duplicate_record_id_is_rejected(tmp_path: Path) -> None:
    first = _record()
    second = copy.deepcopy(first)
    second["sequence"] = 2
    path = tmp_path / "human.jsonl"
    path.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n", encoding="utf-8")

    report = import_human_recording(path)

    assert report.accepted_count == 1
    assert report.rejected_count == 1
    assert report.rejected[0].reason is HumanRecordRejection.DUPLICATE_RECORD_ID
