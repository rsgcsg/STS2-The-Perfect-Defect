from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path

import pytest

from stpd.artifact_contracts import Manifest
from stpd.fullrun.data import admit, publish_dataset, publish_source
from stpd.fullrun.features import (
    compile_features,
    feature_index,
    load_features,
    load_model_view,
    model_samples,
    publish_model_view,
)
from stpd.fullrun.fixtures import SyntheticSourceAdapter, synthetic_bundle
from stpd.fullrun.representation import FullRunSerializer
from stpd.json_boundary import BoundaryError, FrozenObject, json_bytes

from test_artifact_store_v1 import PRODUCER, store


def prepared(tmp_path: Path):
    target = store(tmp_path)
    source, projection = publish_source(target, synthetic_bundle(runs=6),
                                        SyntheticSourceAdapter(), PRODUCER)
    dataset = publish_dataset(target, admit((projection,)), (source,), PRODUCER)
    view = publish_model_view(target, dataset.artifact_id, FullRunSerializer(), PRODUCER)
    return target, dataset, view


def test_model_view_recomputed_from_dataset_and_label_tamper_rejected(tmp_path: Path) -> None:
    target, _, view = prepared(tmp_path)
    _, samples = load_model_view(target, view.artifact_id)
    altered = [sample.to_dict() for sample in samples]
    altered[0]["chosen_index"] = 0
    payload = target.put_payload("samples", io.BytesIO(b"".join(json_bytes(row) for row in altered)))
    forged = replace(view, payloads=(payload,))
    target.publish(forged)
    with pytest.raises(BoundaryError, match="label_mismatch"):
        load_model_view(target, forged.artifact_id)


def test_feature_roundtrip_batch_independence_and_missing_inventory(tmp_path: Path) -> None:
    from stpd.qwen.fake_backend import DeterministicFakeQwenBackend

    target, _, view = prepared(tmp_path)
    backend = DeterministicFakeQwenBackend(hidden_size=8)
    first = compile_features(target, view.artifact_id, backend, PRODUCER, batch_size=2)
    second = compile_features(target, view.artifact_id, backend, PRODUCER, batch_size=7)
    assert first.artifact_id == second.artifact_id
    loaded = load_features(target, first.artifact_id)
    assert loaded.matrix.shape[1] == 8
    assert not loaded.matrix.flags.writeable
    assert len(loaded.samples) == 72
    assert all(len(rows) == len(sample.action_keys) for rows, sample in
               zip(loaded.rows, loaded.samples, strict=True))
    forged = replace(first, payloads=(first.payload("index"),))
    target.publish(forged)
    with pytest.raises(BoundaryError, match="inventory"):
        load_features(target, forged.artifact_id)


def test_feature_index_is_candidate_permutation_equivariant() -> None:
    projection = SyntheticSourceAdapter().project(synthetic_bundle(runs=3))
    dataset = admit((projection,))
    samples = model_samples(dataset, FullRunSerializer())
    changed = tuple(replace(sample, action_texts=tuple(reversed(sample.action_texts)),
                            action_keys=tuple(reversed(sample.action_keys)),
                            chosen_index=len(sample.action_keys) - 1 - sample.chosen_index)
                    for sample in samples)
    identity = FrozenObject.of({"fixture": True})
    keys, rows, _ = feature_index(samples, identity)
    changed_keys, changed_rows, _ = feature_index(changed, identity)
    assert keys == changed_keys
    assert changed_rows == tuple(tuple(reversed(row)) for row in rows)


def test_feature_index_cannot_relabel_or_rebind_candidates(tmp_path: Path) -> None:
    from stpd.qwen.fake_backend import DeterministicFakeQwenBackend

    target, _, view = prepared(tmp_path)
    feature = compile_features(target, view.artifact_id, DeterministicFakeQwenBackend(8), PRODUCER)
    loaded = load_features(target, feature.artifact_id)
    bad_index = {"keys": ["0" * 64] * loaded.matrix.shape[0],
                 "sample_rows": [list(row) for row in loaded.rows]}
    payload = target.put_payload("index", io.BytesIO(json_bytes(bad_index)))
    forged = Manifest("feature_set", PRODUCER, feature.parents,
                       (feature.payload("features"), payload), feature.parameters)
    target.publish(forged)
    with pytest.raises(BoundaryError, match="alignment"):
        load_features(target, forged.artifact_id)
