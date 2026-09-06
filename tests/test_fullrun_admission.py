from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from stpd.fullrun.contracts import SourceProjection
from stpd.fullrun.data import admit, load_dataset, publish_dataset, publish_source
from stpd.fullrun.fixtures import SyntheticSourceAdapter, synthetic_bundle
from stpd.fullrun.representation import decision_fingerprint
from stpd.json_boundary import BoundaryError


def projection(runs: int = 12) -> SourceProjection:
    return SyntheticSourceAdapter().project(synthetic_bundle(runs=runs))


def test_admission_dedup_whole_run_split_and_permutation() -> None:
    source = projection()
    first = admit((source,))
    second = admit((replace(source, transitions=tuple(reversed(source.transitions))), source))
    assert first.logical_id == second.logical_id
    assert second.exact_duplicates == len(source.transitions)
    assert set(first.splits.value().values()) == {"train", "dev", "test"}
    assignments = {}
    for record in first.records:
        partition = first.splits.value()[record.run_id]
        fingerprint = decision_fingerprint(record)
        assert assignments.setdefault(fingerprint, partition) == partition


def test_same_identity_different_content_is_not_deduplicated() -> None:
    source = projection()
    changed = replace(source.transitions[0], chosen_key=source.transitions[0].actions[0].key)
    bad = replace(source, transitions=(changed, *source.transitions[1:]))
    with pytest.raises(BoundaryError, match="identity_collision"):
        admit((source, bad))


def test_incomplete_catalog_missing_steps_and_mixed_scope_fail_closed() -> None:
    source = projection()
    changed = replace(source.transitions[0], catalog_complete=False)
    with pytest.raises(BoundaryError, match="incomplete_or_uncommitted"):
        admit((replace(source, transitions=(changed, *source.transitions[1:])),))
    with pytest.raises(BoundaryError, match="missing_run_step"):
        admit((replace(source, transitions=source.transitions[1:]),))
    other = replace(
        source,
        scope="platform_qualified",
        transitions=tuple(
            replace(r, provenance=replace(r.provenance, scope="platform_qualified"))
            for r in source.transitions
        ),
    )
    with pytest.raises(BoundaryError, match="mixed_engineering"):
        admit((source, other))


def test_repeated_semantic_decisions_join_entire_runs() -> None:
    source = projection()
    rows = list(source.transitions)
    rows[12] = replace(
        rows[12],
        state=rows[0].state,
        actions=rows[0].actions,
        chosen_key=rows[0].chosen_key,
        catalog_count=rows[0].catalog_count,
    )
    joined = admit((replace(source, transitions=tuple(rows)),))
    assert joined.splits.value()[rows[0].run_id] == joined.splits.value()[rows[12].run_id]


def test_parquet_dataset_and_lineage_roundtrip(tmp_path: Path) -> None:
    from test_artifact_store_v1 import PRODUCER, store

    target = store(tmp_path)
    source, projected = publish_source(
        target, synthetic_bundle(runs=6), SyntheticSourceAdapter(), PRODUCER
    )
    dataset = admit((projected,), seed=19)
    manifest = publish_dataset(target, dataset, (source,), PRODUCER)
    restored_manifest, restored = load_dataset(target, manifest.artifact_id)
    assert restored_manifest == manifest
    assert restored.logical_id == dataset.logical_id
    assert restored.splits == dataset.splits
    assert restored.scope == "engineering"
    assert manifest.parent("evidence") == source.artifact_id


def test_new_dataset_identity_cannot_relabel_an_unchanged_source(tmp_path: Path) -> None:
    from test_artifact_store_v1 import PRODUCER, store

    target = store(tmp_path)
    source, projected = publish_source(
        target, synthetic_bundle(runs=6), SyntheticSourceAdapter(), PRODUCER
    )
    changed = replace(projected.transitions[0], chosen_key=projected.transitions[0].actions[0].key)
    forged = admit((replace(projected, transitions=(changed, *projected.transitions[1:])),))
    with pytest.raises(BoundaryError, match="source_transition_projection_mismatch"):
        publish_dataset(target, forged, (source,), PRODUCER)
