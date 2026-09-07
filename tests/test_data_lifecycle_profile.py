from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from stpd.canonical import canonical_json
from stpd.data.lifecycle_profile import LifecycleProfileError, profile_canonical_dataset
from stpd.data.manifest import DataSource
from stpd.data.pipeline import build_canonical_dataset


def _dataset(tmp_path: Path) -> Path:
    fixture = Path(__file__).parent / "fixtures" / "research-transition-v0.golden.json"
    first = json.loads(fixture.read_text(encoding="utf-8"))
    second = copy.deepcopy(first)
    records = [first, second]
    records[0]["step_index"] = 0
    records[1]["step_index"] = 1
    records[1]["transition_id"] = "transition-1"
    records[1]["raw_ref"] = "fixture://transition-1"
    records[0]["successor"] = records[1]["state"]
    output = tmp_path / "dataset"
    build_canonical_dataset(
        records,
        output_dir=output,
        schema_root=Path(__file__).parents[1] / "schemas",
        source=DataSource(
            source_id="fixture",
            kind="test_fixture",
            source_revision="fixture-v1",
            license_spdx="MIT",
            provenance_uri="fixture://profile",
        ),
        stpd_source_revision="test",
        created_at="2026-08-29T00:00:00Z",
        split_salt="profile-test",
    )
    return output


def test_profile_verifies_identity_and_compares_reconstructable_layouts(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    report = profile_canonical_dataset(dataset, read_repeats=2)

    assert report["dataset"]["rows"] == 2
    assert report["semantic_reuse"]["successor_equals_next_state"] == 1
    assert report["semantic_reuse"]["chosen_action_membership_failures"] == 0
    assert report["layout_probes"]["exact_reconstruction"] == {
        "content_addressed_objects": True
    }
    assert report["layout_probes"]["production_migration_authorized"] is False


def test_profile_fails_closed_on_manifest_bound_parquet_tampering(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    parquet = dataset / "transitions.parquet"
    parquet.write_bytes(parquet.read_bytes() + b"tamper")

    with pytest.raises(LifecycleProfileError, match="checksum mismatch"):
        profile_canonical_dataset(dataset)


def test_profile_report_is_json_serializable(tmp_path: Path) -> None:
    report = profile_canonical_dataset(_dataset(tmp_path), probe_layouts=False)
    assert json.loads(canonical_json(report))["schema"] == "stpd/data-lifecycle-profile-v1"
