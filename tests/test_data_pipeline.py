from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from stpd.contracts import ContractError
from stpd.data import (
    DataFile,
    DataManifest,
    DatasetBuildError,
    DataSource,
    SplitAssignment,
    assign_episode_splits,
    build_canonical_dataset,
    read_transition_parquet,
    research_action_from_record,
    research_state_from_record,
    validate_b0,
    write_transition_parquet,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "research-transition-v0.golden.json"


def _record() -> dict:
    return json.loads(FIXTURE.read_text())


def test_parquet_round_trip_preserves_canonical_transition(tmp_path: Path) -> None:
    record = _record()
    path = tmp_path / "transitions.parquet"
    rows, dataset_hash = write_transition_parquet([record], path)
    assert rows == 1 and len(dataset_hash) == 64
    assert read_transition_parquet(path) == [record]


def test_split_assignment_groups_same_seed_and_is_order_independent() -> None:
    first = _record()
    second = copy.deepcopy(first)
    second["transition_id"] = "transition-000002"
    second["episode_id"] = "episode-fixture-2"
    forward = assign_episode_splits([first, second], salt="stpd-v0")
    reverse = assign_episode_splits([second, first], salt="stpd-v0")
    assert forward == reverse
    assert forward[first["episode_id"]].split == forward[second["episode_id"]].split


def test_data_manifest_rejects_unknown_license_and_truncation(tmp_path: Path) -> None:
    parquet = tmp_path / "transitions.parquet"
    rows, dataset_hash = write_transition_parquet([_record()], parquet)
    file = DataFile.from_path(parquet, rows=rows, semantic_hash_=dataset_hash)
    source = DataSource("fixture", "fixture", "v1", "MIT", "https://example.invalid/data")
    manifest = DataManifest(
        "manifest-1",
        "2026-08-22T00:00:00Z",
        "source-sha",
        "stpd/research-transition-v0",
        (source,),
        (file,),
        1,
        {"strategy": "seed_root_hash_v0"},
        {"exact_duplicates": 0},
        {"rank": 1, "transition": 1, "return": 0},
    )
    manifest.validate()
    with pytest.raises(ContractError, match="license"):
        DataSource("fixture", "fixture", "v1", "unknown", "local").validate()
    truncated = replace(manifest, truncation_applied=True)
    with pytest.raises(ContractError, match="truncation"):
        truncated.validate()


def test_b0_accepts_golden_and_rejects_leakage_and_missing_successor() -> None:
    record = _record()
    report = validate_b0([record], schema_root=ROOT / "schemas")
    assert report.verdict == "pass"

    leaked = copy.deepcopy(record)
    leaked["transition_id"] = "leaked"
    leaked["state"]["facts"]["hidden_rng"] = 17
    missing = copy.deepcopy(record)
    missing["transition_id"] = "missing"
    missing["successor"] = None
    failed = validate_b0([leaked, missing], schema_root=ROOT / "schemas")
    assert failed.verdict == "fail"
    assert {finding.code for finding in failed.findings} >= {
        "model_input_leakage",
        "missing_successor",
    }


def test_b0_rejects_semantic_duplicates_crossing_splits() -> None:
    first = _record()
    second = copy.deepcopy(first)
    second["transition_id"] = "transition-000002"
    second["episode_id"] = "episode-2"
    second["raw_ref"] = "raw/fixture/episode-2#0"
    splits = {
        first["episode_id"]: SplitAssignment(first["episode_id"], "root-a", "train"),
        second["episode_id"]: SplitAssignment(second["episode_id"], "root-b", "test"),
    }
    report = validate_b0([first, second], schema_root=ROOT / "schemas", splits=splits)
    assert report.verdict == "fail"
    assert "cross_split_semantic_duplicate" in {item.code for item in report.findings}


def test_pipeline_writes_checksums_manifest_and_fails_before_bad_output(tmp_path: Path) -> None:
    source = DataSource("fixture", "fixture", "v1", "MIT", "https://example.invalid/data")
    output = tmp_path / "canonical"
    manifest, report = build_canonical_dataset(
        [_record()],
        output_dir=output,
        schema_root=ROOT / "schemas",
        source=source,
        stpd_source_revision="source-sha",
        created_at="2026-08-22T00:00:00Z",
        split_salt="stpd-v0",
    )
    assert report.verdict == "pass" and manifest.row_count == 1
    assert (output / "transitions.parquet").is_file()
    assert json.loads((output / "manifest.json").read_text())["manifest_id"] == manifest.manifest_id
    serialized_manifest = json.loads((output / "manifest.json").read_text())
    assert serialized_manifest["split"]["assignments"] == {
        "episode-fixture": next(iter(serialized_manifest["split"]["assignments"].values()))
    }

    bad = _record()
    bad["successor"] = None
    rejected_output = tmp_path / "rejected"
    with pytest.raises(DatasetBuildError, match="missing_successor"):
        build_canonical_dataset(
            [bad],
            output_dir=rejected_output,
            schema_root=ROOT / "schemas",
            source=source,
            stpd_source_revision="source-sha",
            created_at="2026-08-22T00:00:00Z",
            split_salt="stpd-v0",
        )
    assert not rejected_output.exists()


def test_strict_record_reconstruction_preserves_state_and_actions() -> None:
    record = _record()
    state = research_state_from_record(record["state"])
    actions = [research_action_from_record(value) for value in record["legal_actions"]]
    assert state.to_dict() == record["state"]
    assert [action.to_dict() for action in actions] == record["legal_actions"]

    broken = copy.deepcopy(record["state"])
    broken["state_hash"] = "0" * 64
    with pytest.raises(ContractError, match="hash"):
        research_state_from_record(broken)
