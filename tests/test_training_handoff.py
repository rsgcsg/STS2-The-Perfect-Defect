from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from stpd.data.manifest import DataSource
from stpd.data.pipeline import build_canonical_dataset
from stpd.data.training_handoff import (
    TrainingHandoffError,
    build_training_input,
    resolve_training_object,
    stage_training_input,
    verify_training_input,
)


def _dataset(tmp_path: Path) -> Path:
    fixture = Path(__file__).parent / "fixtures" / "research-transition-v0.golden.json"
    record = json.loads(fixture.read_text(encoding="utf-8"))
    output = tmp_path / "dataset"
    build_canonical_dataset(
        [record],
        output_dir=output,
        schema_root=Path(__file__).parents[1] / "schemas",
        source=DataSource("fixture", "fixture", "v1", "MIT", "fixture://handoff"),
        stpd_source_revision="test",
        created_at="2026-08-29T00:00:00Z",
        split_salt="handoff-test",
    )
    return output


def _qwen() -> dict[str, object]:
    return {
        "model_id": "Qwen/Qwen3-0.6B-Base",
        "model_revision": "a" * 40,
        "tokenizer_revision": "a" * 40,
        "tokenizer_sha256": "b" * 64,
        "weights_sha256": "c" * 64,
        "dtype": "bfloat16",
        "feature_dtype": "float32",
        "pooling": "masked_mean",
    }


def _consumer() -> dict[str, str]:
    return {
        "repository": "rsgcsg/STS2-The-Perfect-Defect",
        "source_revision": "d" * 40,
        "uv_lock_sha256": "e" * 64,
        "entry_point": "uv run python tools/s1_smoke.py run",
    }


def _validate_manifest(manifest: dict[str, object]) -> None:
    root = Path(__file__).parents[1]
    schema = json.loads(
        (root / "schemas" / "training-input-manifest-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(manifest)


def test_training_input_stages_only_missing_objects_and_never_authorizes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    receiver = tmp_path / "receiver"
    manifest = build_training_input(
        dataset_directory=_dataset(tmp_path),
        store_directory=source,
        lane="scheme1-canonical",
        serializer_version="stpd-model-serialization-v1",
        input_profile="stpd-combat-v0-standard",
        qwen_identity=_qwen(),
        consumer_identity=_consumer(),
    )
    training_input_id = manifest["training_input_id"]
    _validate_manifest(manifest)

    first = stage_training_input(
        source_store=source,
        receiver_store=receiver,
        training_input_id=training_input_id,
    )
    second = stage_training_input(
        source_store=source,
        receiver_store=receiver,
        training_input_id=training_input_id,
    )

    assert first["transferred_objects"] == 2
    assert second["transferred_objects"] == 0
    assert second["reused_objects"] == 2
    assert first["training_authorized"] is False
    assert verify_training_input(receiver, training_input_id)["training_authorized"] is False
    assert resolve_training_object(
        receiver, training_input_id, "canonical/transitions.parquet"
    ).is_file()


def test_new_derived_object_transfers_incrementally_without_mutating_old_input(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path)
    source = tmp_path / "source"
    receiver = tmp_path / "receiver"
    first = build_training_input(
        dataset_directory=dataset,
        store_directory=source,
        lane="scheme1-canonical",
        serializer_version="stpd-model-serialization-v1",
        input_profile="stpd-combat-v0-standard",
        qwen_identity=_qwen(),
        consumer_identity=_consumer(),
    )
    stage_training_input(
        source_store=source,
        receiver_store=receiver,
        training_input_id=first["training_input_id"],
    )
    feature = tmp_path / "features.npy"
    feature.write_bytes(b"derived-feature-fixture")
    second = build_training_input(
        dataset_directory=dataset,
        store_directory=source,
        lane="scheme1-pooled",
        serializer_version="stpd-model-serialization-v1",
        input_profile="stpd-combat-v0-standard",
        qwen_identity=_qwen(),
        consumer_identity=_consumer(),
        derived_artifacts=(
            (feature, "features/features.npy", "DERIVED_FEATURE_CACHE", "pooled_features"),
        ),
    )
    receipt = stage_training_input(
        source_store=source,
        receiver_store=receiver,
        training_input_id=second["training_input_id"],
    )

    assert first["training_input_id"] != second["training_input_id"]
    assert receipt["transferred_objects"] == 1
    assert receipt["reused_objects"] == 2
    assert verify_training_input(receiver, first["training_input_id"])["status"].startswith(
        "integrity_ready"
    )


def test_receiver_corruption_fails_closed_without_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source"
    receiver = tmp_path / "receiver"
    manifest = build_training_input(
        dataset_directory=_dataset(tmp_path),
        store_directory=source,
        lane="scheme1-canonical",
        serializer_version="stpd-model-serialization-v1",
        input_profile="stpd-combat-v0-standard",
        qwen_identity=_qwen(),
        consumer_identity=_consumer(),
    )
    training_input_id = manifest["training_input_id"]
    stage_training_input(
        source_store=source,
        receiver_store=receiver,
        training_input_id=training_input_id,
    )
    object_entry = manifest["objects"][0]
    digest = object_entry["sha256"]
    object_path = receiver / "objects" / "sha256" / digest[:2] / digest
    object_path.write_bytes(b"corrupt")

    with pytest.raises(TrainingHandoffError, match="refusing overwrite"):
        stage_training_input(
            source_store=source,
            receiver_store=receiver,
            training_input_id=training_input_id,
        )


def test_expected_model_view_drift_fails_closed(tmp_path: Path) -> None:
    store = tmp_path / "store"
    manifest = build_training_input(
        dataset_directory=_dataset(tmp_path),
        store_directory=store,
        lane="scheme1-canonical",
        serializer_version="stpd-model-serialization-v1",
        input_profile="stpd-combat-v0-standard",
        qwen_identity=_qwen(),
        consumer_identity=_consumer(),
    )
    with pytest.raises(TrainingHandoffError, match="model-view identity mismatch"):
        verify_training_input(
            store,
            manifest["training_input_id"],
            expected_model_view={"serializer_version": "wrong"},
        )


def test_expected_consumer_drift_fails_closed(tmp_path: Path) -> None:
    store = tmp_path / "store"
    manifest = build_training_input(
        dataset_directory=_dataset(tmp_path),
        store_directory=store,
        lane="scheme1-canonical",
        serializer_version="stpd-model-serialization-v1",
        input_profile="stpd-combat-v0-standard",
        qwen_identity=_qwen(),
        consumer_identity=_consumer(),
    )
    with pytest.raises(TrainingHandoffError, match="consumer identity mismatch"):
        verify_training_input(
            store,
            manifest["training_input_id"],
            expected_consumer={**_consumer(), "source_revision": "f" * 40},
        )
