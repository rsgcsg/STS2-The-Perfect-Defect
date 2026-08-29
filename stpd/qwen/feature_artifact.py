"""Immutable pooled-feature artifacts derived from canonical STPD data.

Feature artifacts are disposable caches. Their manifests bind the exact source
dataset, serializer, and frozen encoder identity so a training host can reuse
expensive backbone work without confusing it with canonical research truth.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ..canonical import canonical_json, semantic_hash, to_json_value
from ..contracts import ContractError, QwenBackend
from ..data.lifecycle_profile import profile_canonical_dataset
from ..data.parquet import read_transition_parquet
from ..representation import InputProfile, model_serializer

FEATURE_MANIFEST_SCHEMA = "stpd/frozen-joint-feature-manifest-v1"


class FeatureArtifactError(ContractError):
    """Raised when frozen features cannot be compiled or verified exactly."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(backend: QwenBackend) -> dict[str, Any]:
    value = backend.identity
    if is_dataclass(value):
        encoded = asdict(value)
    elif isinstance(value, Mapping):
        encoded = dict(value)
    elif hasattr(value, "__dict__"):
        encoded = dict(vars(value))
    else:
        raise FeatureArtifactError("Qwen backend identity is not serializable")
    result = to_json_value(encoded)
    if not isinstance(result, dict) or not result:
        raise FeatureArtifactError("Qwen backend identity must be a non-empty object")
    return result


def _numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "float") and str(getattr(value, "dtype", "")) == "torch.bfloat16":
        value = value.float()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    result = np.asarray(value)
    if result.ndim != 2 or result.shape[0] <= 0 or result.shape[1] <= 0:
        raise FeatureArtifactError("joint encoder output must be [sample, hidden]")
    if not np.issubdtype(result.dtype, np.floating) or not np.isfinite(result).all():
        raise FeatureArtifactError("joint encoder output must contain finite floating values")
    return np.asarray(result, dtype=np.float32, order="C")


def _atomic_directory(temporary: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing_manifest = destination / "manifest.json"
        candidate_manifest = temporary / "manifest.json"
        if (
            not existing_manifest.is_file()
            or existing_manifest.read_bytes() != candidate_manifest.read_bytes()
        ):
            raise FeatureArtifactError("immutable feature artifact collision")
        shutil.rmtree(temporary)
        return destination
    os.replace(temporary, destination)
    return destination


def _manifest_files(directory: Path, names: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "path": name,
            "sha256": _sha256(directory / name),
            "bytes": (directory / name).stat().st_size,
        }
        for name in names
    ]


def compile_joint_feature_artifact(
    *,
    dataset_directory: str | Path,
    output_root: str | Path,
    backend: QwenBackend,
    serializer_version: str,
    input_profile: str,
    batch_size: int = 8,
) -> Path:
    """Compile deduplicated Scheme1 pooled joint features into an immutable artifact."""

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    try:
        profile = InputProfile(input_profile)
    except ValueError as error:
        raise FeatureArtifactError("unsupported input profile") from error
    serializer = model_serializer(serializer_version, profile)
    dataset = Path(dataset_directory).expanduser().resolve()
    source = profile_canonical_dataset(dataset, read_repeats=1, probe_layouts=False)
    source_identity = dict(source["dataset"])
    records = read_transition_parquet(dataset / "transitions.parquet")
    qwen_identity = _identity(backend)

    feature_inputs: dict[str, tuple[str, str, dict[str, Any]]] = {}
    samples: list[dict[str, Any]] = []
    rank_transition_ids: set[str] = set()
    for record in records:
        eligibility = record.get("eligibility")
        if not isinstance(eligibility, Mapping) or eligibility.get("rank") is not True:
            continue
        rank_transition_ids.add(str(record["transition_id"]))
        state = record["state"]
        actions = record["legal_actions"]
        if not isinstance(actions, list) or not actions:
            raise FeatureArtifactError("rank-eligible record has no ordered action catalog")
        state_text = serializer.serialize_state(state)
        chosen_key = str(record["chosen_action"].get("action_key", ""))
        if not chosen_key:
            raise FeatureArtifactError("chosen action key is absent")
        for candidate_index, action in enumerate(actions):
            action_text = serializer.serialize_action(action)
            key_payload = {
                "schema": "stpd/frozen-joint-feature-key-v1",
                "state_hash": semantic_hash(state),
                "action_hash": semantic_hash(action),
                "state_text_sha256": hashlib.sha256(state_text.encode("utf-8")).hexdigest(),
                "action_text_sha256": hashlib.sha256(action_text.encode("utf-8")).hexdigest(),
                "serializer_version": serializer_version,
                "input_profile": input_profile,
                "qwen_identity": qwen_identity,
                "operation": "encode_joint_masked_mean",
                "storage_dtype": "float32",
            }
            feature_key = semantic_hash(key_payload)
            existing = feature_inputs.setdefault(
                feature_key, (state_text, action_text, key_payload)
            )
            if existing != (state_text, action_text, key_payload):
                raise FeatureArtifactError("feature key collision")
            samples.append(
                {
                    "transition_id": record["transition_id"],
                    "episode_id": record["episode_id"],
                    "step_index": record["step_index"],
                    "candidate_index": candidate_index,
                    "action_key": action.get("action_key"),
                    "chosen": action.get("action_key") == chosen_key,
                    "feature_key": feature_key,
                }
            )
    if not samples:
        raise FeatureArtifactError("dataset has no rank-eligible candidate samples")
    chosen_by_transition: dict[str, int] = {}
    for sample in samples:
        if sample["chosen"]:
            transition_id = str(sample["transition_id"])
            chosen_by_transition[transition_id] = chosen_by_transition.get(transition_id, 0) + 1
    if (
        set(chosen_by_transition) != rank_transition_ids
        or set(chosen_by_transition.values()) != {1}
    ):
        raise FeatureArtifactError(
            "each rank-eligible transition must select exactly one candidate"
        )

    ordered_keys = sorted(feature_inputs)
    rows: list[np.ndarray] = []
    for start in range(0, len(ordered_keys), batch_size):
        keys = ordered_keys[start : start + batch_size]
        encoded = _numpy(
            backend.encode_joint(
                [feature_inputs[key][0] for key in keys],
                [feature_inputs[key][1] for key in keys],
            )
        )
        if encoded.shape[0] != len(keys):
            raise FeatureArtifactError("joint encoder changed candidate cardinality")
        rows.append(encoded)
    features = np.concatenate(rows, axis=0)
    if features.shape[0] != len(ordered_keys):
        raise FeatureArtifactError("compiled feature count mismatch")
    row_by_key = {key: row for row, key in enumerate(ordered_keys)}
    for sample in samples:
        sample["feature_row"] = row_by_key[str(sample["feature_key"])]

    payload = {
        "schema": FEATURE_MANIFEST_SCHEMA,
        "source_dataset": {
            "manifest_id": source_identity["manifest_id"],
            "manifest_sha256": source_identity["manifest_sha256"],
            "semantic_dataset_hash": source_identity["semantic_dataset_hash"],
            "rows": source_identity["rows"],
        },
        "training_view": {
            "lane": "scheme1-pooled-joint",
            "compiler_version": "stpd-joint-feature-compiler-v1",
            "serializer_version": serializer_version,
            "input_profile": input_profile,
            "qwen_identity": qwen_identity,
            "operation": "encode_joint_masked_mean",
            "storage_dtype": "float32",
            "feature_schema": "pooled-joint-v1",
        },
        "shape": [int(features.shape[0]), int(features.shape[1])],
        "sample_count": len(samples),
        "unique_feature_count": len(ordered_keys),
        "training_authorized": False,
        "retention_class": "rebuildable_derived_feature_cache",
    }
    feature_spec_id = semantic_hash(payload)
    output = Path(output_root).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".joint-features-", dir=output))
    destination: Path | None = None
    try:
        np.save(temporary / "features.npy", features, allow_pickle=False)
        (temporary / "feature-index.json").write_text(
            canonical_json(
                {
                    "schema": "stpd/frozen-joint-feature-index-v1",
                    "keys": [
                        {"feature_key": key, "feature_row": row}
                        for row, key in enumerate(ordered_keys)
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        pq.write_table(
            pa.Table.from_pylist(samples),
            temporary / "samples.parquet",
            compression="zstd",
            use_dictionary=True,
            write_statistics=True,
            data_page_version="2.0",
        )
        files = _manifest_files(
            temporary, ("features.npy", "feature-index.json", "samples.parquet")
        )
        artifact_id = semantic_hash({**payload, "files": files})
        destination = output / f"joint-features-{artifact_id[:16]}"
        manifest_payload = {
            **payload,
            "feature_spec_id": feature_spec_id,
            "artifact_id": artifact_id,
            "files": files,
        }
        manifest_payload["manifest_content_id"] = semantic_hash(manifest_payload)
        (temporary / "manifest.json").write_text(
            canonical_json(manifest_payload) + "\n", encoding="utf-8"
        )
        destination = _atomic_directory(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    if destination is None:
        raise FeatureArtifactError("feature artifact destination was not established")
    verify_joint_feature_artifact(destination)
    return destination


def verify_joint_feature_artifact(directory: str | Path) -> dict[str, Any]:
    """Verify a compiled feature artifact without requiring Qwen or game files."""

    root = Path(directory).expanduser().resolve()
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FeatureArtifactError("feature manifest is missing or invalid") from error
    if not isinstance(manifest, dict) or manifest.get("schema") != FEATURE_MANIFEST_SCHEMA:
        raise FeatureArtifactError("unsupported feature manifest schema")
    manifest_without_content = {
        key: value for key, value in manifest.items() if key != "manifest_content_id"
    }
    if manifest.get("manifest_content_id") != semantic_hash(manifest_without_content):
        raise FeatureArtifactError("feature manifest content identity mismatch")
    payload_keys = {
        "schema",
        "source_dataset",
        "training_view",
        "shape",
        "sample_count",
        "unique_feature_count",
        "training_authorized",
        "retention_class",
    }
    artifact_payload = {key: manifest[key] for key in payload_keys}
    if manifest.get("feature_spec_id") != semantic_hash(artifact_payload):
        raise FeatureArtifactError("feature specification identity mismatch")
    if manifest.get("artifact_id") != semantic_hash(
        {**artifact_payload, "files": manifest.get("files")}
    ):
        raise FeatureArtifactError("feature artifact identity mismatch")
    for value in manifest.get("files", []):
        if not isinstance(value, Mapping):
            raise FeatureArtifactError("feature file inventory entry must be an object")
        path = root / str(value.get("path", ""))
        if not path.is_file() or _sha256(path) != value.get("sha256"):
            raise FeatureArtifactError("feature file is missing or corrupt")
        if path.stat().st_size != value.get("bytes"):
            raise FeatureArtifactError("feature file size mismatch")
    features = np.load(root / "features.npy", mmap_mode="r", allow_pickle=False)
    if list(features.shape) != manifest.get("shape") or features.dtype != np.float32:
        raise FeatureArtifactError("feature tensor shape or dtype mismatch")
    samples = pq.read_table(root / "samples.parquet").to_pylist()
    if len(samples) != manifest.get("sample_count"):
        raise FeatureArtifactError("feature sample cardinality mismatch")
    if any(
        not isinstance(sample.get("feature_row"), int)
        or sample["feature_row"] < 0
        or sample["feature_row"] >= features.shape[0]
        for sample in samples
    ):
        raise FeatureArtifactError("feature sample references an invalid feature row")
    return {
        "schema": "stpd/frozen-joint-feature-verification-v1",
        "status": "verified_rebuildable_cache",
        "artifact_id": manifest["artifact_id"],
        "shape": list(features.shape),
        "sample_count": len(samples),
        "bytes": sum(int(item["bytes"]) for item in manifest["files"]),
        "training_authorized": False,
    }
