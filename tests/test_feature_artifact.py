from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from stpd.data.manifest import DataSource
from stpd.data.pipeline import build_canonical_dataset
from stpd.data.training_handoff import (
    build_training_input,
    stage_training_input,
    verify_training_input,
)
from stpd.qwen.feature_artifact import (
    FeatureArtifactError,
    compile_joint_feature_artifact,
    verify_joint_feature_artifact,
)


@dataclass(frozen=True)
class _Identity:
    model_id: str = "fixture/frozen"
    model_revision: str = "a" * 40
    tokenizer_revision: str = "a" * 40
    tokenizer_sha256: str = "b" * 64
    weights_sha256: str = "c" * 64
    feature_dtype: str = "float32"
    pooling: str = "masked_mean"


class _Backend:
    def __init__(self, revision: str = "a" * 40) -> None:
        self.identity = _Identity(model_revision=revision, tokenizer_revision=revision)
        self.calls = 0

    def encode_joint(self, state_texts: list[str], action_texts: list[str]) -> np.ndarray:
        self.calls += 1
        return np.asarray(
            [
                [len(state), len(action), sum(state.encode()) % 997, sum(action.encode()) % 991]
                for state, action in zip(state_texts, action_texts, strict=True)
            ],
            dtype=np.float32,
        )

    def encode_state(self, state_texts: list[str], *, return_sequence: bool) -> np.ndarray:
        raise NotImplementedError

    def embed_action_tokens(self, action_texts: list[str]) -> np.ndarray:
        raise NotImplementedError


def _dataset(tmp_path: Path) -> Path:
    fixture = Path(__file__).parent / "fixtures" / "research-transition-v0.golden.json"
    record = json.loads(fixture.read_text(encoding="utf-8"))
    output = tmp_path / "dataset"
    build_canonical_dataset(
        [record],
        output_dir=output,
        schema_root=Path(__file__).parents[1] / "schemas",
        source=DataSource("fixture", "fixture", "v1", "MIT", "fixture://features"),
        stpd_source_revision="test",
        created_at="2026-08-29T00:00:00Z",
        split_salt="features-test",
    )
    return output


def _consumer() -> dict[str, str]:
    return {
        "repository": "rsgcsg/STS2-The-Perfect-Defect",
        "source_revision": "d" * 40,
        "uv_lock_sha256": "e" * 64,
        "entry_point": "uv run python tools/s1_smoke.py run",
    }


def _validate_manifest(artifact: Path) -> None:
    root = Path(__file__).parents[1]
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    schema = json.loads(
        (root / "schemas" / "frozen-joint-feature-manifest-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(manifest)


def test_compiler_is_immutable_deterministic_and_deduplicates_candidates(tmp_path: Path) -> None:
    backend = _Backend()
    first = compile_joint_feature_artifact(
        dataset_directory=_dataset(tmp_path),
        output_root=tmp_path / "features",
        backend=backend,
        serializer_version="stpd-model-serialization-v1",
        input_profile="stpd-combat-v0-standard",
        batch_size=2,
    )
    retry = compile_joint_feature_artifact(
        dataset_directory=tmp_path / "dataset",
        output_root=tmp_path / "features",
        backend=_Backend(),
        serializer_version="stpd-model-serialization-v1",
        input_profile="stpd-combat-v0-standard",
        batch_size=3,
    )
    report = verify_joint_feature_artifact(first)
    _validate_manifest(first)

    assert retry == first
    assert report["status"] == "verified_rebuildable_cache"
    assert report["training_authorized"] is False
    assert report["shape"][1] == 4
    assert backend.calls >= 1


def test_encoder_identity_change_invalidates_artifact_identity(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    first = compile_joint_feature_artifact(
        dataset_directory=dataset,
        output_root=tmp_path / "features",
        backend=_Backend("a" * 40),
        serializer_version="stpd-model-serialization-v1",
        input_profile="stpd-combat-v0-standard",
    )
    second = compile_joint_feature_artifact(
        dataset_directory=dataset,
        output_root=tmp_path / "features",
        backend=_Backend("d" * 40),
        serializer_version="stpd-model-serialization-v1",
        input_profile="stpd-combat-v0-standard",
    )
    assert first != second


def test_feature_tampering_fails_closed(tmp_path: Path) -> None:
    artifact = compile_joint_feature_artifact(
        dataset_directory=_dataset(tmp_path),
        output_root=tmp_path / "features",
        backend=_Backend(),
        serializer_version="stpd-model-serialization-v1",
        input_profile="stpd-combat-v0-standard",
    )
    (artifact / "features.npy").write_bytes(b"tampered")
    with pytest.raises(FeatureArtifactError, match="missing or corrupt"):
        verify_joint_feature_artifact(artifact)


def test_feature_artifact_is_bound_and_verified_by_training_input(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    backend = _Backend()
    artifact = compile_joint_feature_artifact(
        dataset_directory=dataset,
        output_root=tmp_path / "features",
        backend=backend,
        serializer_version="stpd-model-serialization-v1",
        input_profile="stpd-combat-v0-standard",
    )
    source = tmp_path / "source-store"
    receiver = tmp_path / "receiver-store"
    manifest = build_training_input(
        dataset_directory=dataset,
        store_directory=source,
        lane="scheme1-pooled-joint",
        serializer_version="stpd-model-serialization-v1",
        input_profile="stpd-combat-v0-standard",
        qwen_identity=vars(backend.identity),
        consumer_identity=_consumer(),
        feature_artifact_directory=artifact,
    )
    receipt = stage_training_input(
        source_store=source,
        receiver_store=receiver,
        training_input_id=manifest["training_input_id"],
    )

    assert manifest["derived_feature_artifact"]["artifact_id"]
    assert receipt["transferred_objects"] == 6
    assert verify_training_input(receiver, manifest["training_input_id"])["status"].startswith(
        "integrity_ready"
    )
