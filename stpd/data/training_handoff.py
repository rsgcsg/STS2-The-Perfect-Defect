"""Manifest-first, content-addressed staging for real training hosts.

The handoff contains only explicit canonical/derived artifacts. It never grants
training authorization and never treats a cache as research or evidence truth.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..canonical import canonical_json, semantic_hash
from ..contracts import ContractError
from .lifecycle_profile import profile_canonical_dataset

TRAINING_INPUT_SCHEMA = "stpd/training-input-manifest-v1"
STAGING_RECEIPT_SCHEMA = "stpd/training-input-staging-receipt-v1"


class TrainingHandoffError(ContractError):
    """Raised when a training input cannot be created or verified exactly."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TrainingHandoffError(f"{name} must be an object")
    return value


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TrainingHandoffError(f"{name} must be an array")
    return value


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _object_path(store: Path, digest: str) -> Path:
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise TrainingHandoffError("object digest must be lowercase SHA-256")
    return store / "objects" / "sha256" / digest[:2] / digest


def _put_object(store: Path, source: Path) -> dict[str, Any]:
    digest = _sha256(source)
    destination = _object_path(store, digest)
    if destination.exists():
        if _sha256(destination) != digest or destination.stat().st_size != source.stat().st_size:
            raise TrainingHandoffError("content-addressed object collision or corruption")
    else:
        _atomic_copy(source, destination)
    return {"sha256": digest, "bytes": source.stat().st_size}


def _load_manifest(store: Path, training_input_id: str) -> dict[str, Any]:
    path = store / "manifests" / f"{training_input_id}.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TrainingHandoffError("training-input manifest is missing or invalid") from error
    manifest = dict(_object(manifest, "training-input manifest"))
    if manifest.get("schema") != TRAINING_INPUT_SCHEMA:
        raise TrainingHandoffError("unsupported training-input manifest schema")
    supplied_id = manifest.get("training_input_id")
    identity_payload = {key: value for key, value in manifest.items() if key != "training_input_id"}
    if supplied_id != semantic_hash(identity_payload) or supplied_id != training_input_id:
        raise TrainingHandoffError("training-input manifest identity mismatch")
    return manifest


def _declared_artifact(
    *, source: Path, logical_path: str, artifact_class: str, role: str
) -> tuple[Path, dict[str, Any]]:
    if not source.is_file():
        raise TrainingHandoffError(f"declared training artifact is missing: {source}")
    if Path(logical_path).is_absolute() or ".." in Path(logical_path).parts:
        raise TrainingHandoffError("training artifact logical_path must be portable and relative")
    if artifact_class not in {
        "CANONICAL_RESEARCH",
        "DERIVED_MODEL_VIEW",
        "DERIVED_FEATURE_CACHE",
    }:
        raise TrainingHandoffError("unsupported training artifact class")
    return source, {
        "logical_path": logical_path,
        "artifact_class": artifact_class,
        "role": role,
    }


def build_training_input(
    *,
    dataset_directory: str | Path,
    store_directory: str | Path,
    lane: str,
    serializer_version: str,
    input_profile: str,
    qwen_identity: Mapping[str, Any],
    consumer_identity: Mapping[str, Any],
    feature_artifact_directory: str | Path | None = None,
    derived_artifacts: Sequence[tuple[str | Path, str, str, str]] = (),
) -> dict[str, Any]:
    """Build one immutable training-input manifest and content-addressed object set.

    ``derived_artifacts`` entries are ``(source, logical_path, artifact_class, role)``.
    The canonical dataset remains the reconstruction authority for every derived file.
    """

    if not lane.strip() or not serializer_version.strip() or not input_profile.strip():
        raise TrainingHandoffError("lane and model-view identity fields must be non-empty")
    qwen = dict(_object(qwen_identity, "qwen_identity"))
    if not qwen:
        raise TrainingHandoffError("qwen_identity must be explicit")
    consumer = dict(_object(consumer_identity, "consumer_identity"))
    required_consumer = {"repository", "source_revision", "uv_lock_sha256", "entry_point"}
    if set(consumer) != required_consumer:
        raise TrainingHandoffError(
            "consumer_identity must contain repository, source_revision, uv_lock_sha256, "
            "and entry_point"
        )
    if consumer["repository"] != "rsgcsg/STS2-The-Perfect-Defect":
        raise TrainingHandoffError("training input has an unexpected consumer repository")
    for name in ("source_revision", "uv_lock_sha256"):
        value = consumer[name]
        expected_length = 40 if name == "source_revision" else 64
        if (
            not isinstance(value, str)
            or len(value) != expected_length
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise TrainingHandoffError(f"consumer {name} must be an exact lowercase digest")
    if not isinstance(consumer["entry_point"], str) or not consumer["entry_point"].strip():
        raise TrainingHandoffError("consumer entry_point must be explicit")
    dataset = Path(dataset_directory).expanduser().resolve()
    store = Path(store_directory).expanduser().resolve()
    profile = profile_canonical_dataset(dataset, read_repeats=1, probe_layouts=False)
    dataset_identity = dict(_object(profile["dataset"], "dataset profile identity"))
    feature_binding: dict[str, Any] | None = None

    artifacts = [
        _declared_artifact(
            source=dataset / "manifest.json",
            logical_path="canonical/manifest.json",
            artifact_class="CANONICAL_RESEARCH",
            role="dataset_manifest",
        ),
        _declared_artifact(
            source=dataset / "transitions.parquet",
            logical_path="canonical/transitions.parquet",
            artifact_class="CANONICAL_RESEARCH",
            role="research_transitions",
        ),
    ]
    if feature_artifact_directory is not None:
        from ..qwen.feature_artifact import verify_joint_feature_artifact

        feature_root = Path(feature_artifact_directory).expanduser().resolve()
        verify_joint_feature_artifact(feature_root)
        feature_manifest = dict(
            _object(
                json.loads((feature_root / "manifest.json").read_text(encoding="utf-8")),
                "feature manifest",
            )
        )
        source_dataset = _object(feature_manifest.get("source_dataset"), "feature source")
        if any(
            source_dataset.get(key) != dataset_identity[key]
            for key in ("manifest_id", "manifest_sha256", "semantic_dataset_hash", "rows")
        ):
            raise TrainingHandoffError("feature artifact source dataset drift")
        training_view = _object(feature_manifest.get("training_view"), "feature training view")
        if (
            training_view.get("serializer_version") != serializer_version
            or training_view.get("input_profile") != input_profile
            or training_view.get("qwen_identity") != qwen
        ):
            raise TrainingHandoffError("feature artifact model-view drift")
        feature_artifact_id = str(feature_manifest.get("artifact_id", ""))
        feature_prefix = f"features/{feature_artifact_id}"
        artifacts.append(
            _declared_artifact(
                source=feature_root / "manifest.json",
                logical_path=f"{feature_prefix}/manifest.json",
                artifact_class="DERIVED_FEATURE_CACHE",
                role="feature_manifest",
            )
        )
        for value in _sequence(feature_manifest.get("files"), "feature files"):
            item = _object(value, "feature file")
            name = str(item.get("path", ""))
            artifacts.append(
                _declared_artifact(
                    source=feature_root / name,
                    logical_path=f"{feature_prefix}/{name}",
                    artifact_class="DERIVED_FEATURE_CACHE",
                    role=f"feature_{Path(name).stem}",
                )
            )
        feature_binding = {
            "artifact_id": feature_artifact_id,
            "feature_spec_id": feature_manifest.get("feature_spec_id"),
            "manifest_content_id": feature_manifest.get("manifest_content_id"),
            "manifest_logical_path": f"{feature_prefix}/manifest.json",
            "shape": feature_manifest.get("shape"),
            "sample_count": feature_manifest.get("sample_count"),
        }
    artifacts.extend(
        _declared_artifact(
            source=Path(source).expanduser().resolve(),
            logical_path=logical_path,
            artifact_class=artifact_class,
            role=role,
        )
        for source, logical_path, artifact_class, role in derived_artifacts
    )
    logical_paths = [item[1]["logical_path"] for item in artifacts]
    if len(logical_paths) != len(set(logical_paths)):
        raise TrainingHandoffError("training input contains duplicate logical paths")

    objects = []
    for source, declaration in sorted(artifacts, key=lambda item: item[1]["logical_path"]):
        stored = _put_object(store, source)
        objects.append({**declaration, **stored})
    payload = {
        "schema": TRAINING_INPUT_SCHEMA,
        "lane": lane,
        "source_dataset": {
            "manifest_id": dataset_identity["manifest_id"],
            "manifest_sha256": dataset_identity["manifest_sha256"],
            "semantic_dataset_hash": dataset_identity["semantic_dataset_hash"],
            "rows": dataset_identity["rows"],
        },
        "model_view": {
            "serializer_version": serializer_version,
            "input_profile": input_profile,
            "qwen_identity": qwen,
        },
        "consumer": consumer,
        "derived_feature_artifact": feature_binding,
        "objects": objects,
        "training_authorized": False,
        "authorization_owner": "STPD owner/scientific workflow",
        "retention": {
            "canonical_research": "durable",
            "derived_model_view": "rebuildable",
            "derived_feature_cache": "rebuildable",
            "training_outputs": "separate_artifact_class",
        },
        "non_claims": [
            "Integrity-ready staging does not authorize optimizer creation.",
            "Derived artifacts do not replace canonical research or Platform evidence authority.",
        ],
    }
    training_input_id = semantic_hash(payload)
    manifest = {**payload, "training_input_id": training_input_id}
    manifest_path = store / "manifests" / f"{training_input_id}.json"
    encoded = canonical_json(manifest) + "\n"
    if manifest_path.exists():
        if manifest_path.read_text(encoding="utf-8") != encoded:
            raise TrainingHandoffError("immutable training-input manifest collision")
    else:
        _atomic_write(manifest_path, encoded)
    return manifest


def verify_training_input(
    store_directory: str | Path,
    training_input_id: str,
    *,
    expected_lane: str | None = None,
    expected_model_view: Mapping[str, Any] | None = None,
    expected_consumer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed unless every required object and applicable identity matches."""

    store = Path(store_directory).expanduser().resolve()
    manifest = _load_manifest(store, training_input_id)
    if expected_lane is not None and manifest.get("lane") != expected_lane:
        raise TrainingHandoffError("training lane identity mismatch")
    if expected_model_view is not None and manifest.get("model_view") != dict(expected_model_view):
        raise TrainingHandoffError("training model-view identity mismatch")
    if expected_consumer is not None and manifest.get("consumer") != dict(expected_consumer):
        raise TrainingHandoffError("training consumer identity mismatch")
    objects = _sequence(manifest.get("objects"), "training-input objects")
    logical_paths: set[str] = set()
    total_bytes = 0
    for value in objects:
        item = _object(value, "training-input object")
        logical_path = str(item.get("logical_path", ""))
        if not logical_path or logical_path in logical_paths:
            raise TrainingHandoffError("training-input logical paths are empty or duplicated")
        logical_paths.add(logical_path)
        digest = str(item.get("sha256", ""))
        path = _object_path(store, digest)
        if not path.is_file() or _sha256(path) != digest:
            raise TrainingHandoffError(f"training-input object is missing or corrupt: {digest}")
        if path.stat().st_size != item.get("bytes"):
            raise TrainingHandoffError("training-input object size mismatch")
        total_bytes += path.stat().st_size
    _verify_feature_binding(store, manifest, objects)
    return {
        "schema": "stpd/training-input-verification-v1",
        "status": "integrity_ready_authorization_required",
        "training_input_id": training_input_id,
        "object_count": len(objects),
        "total_bytes": total_bytes,
        "training_authorized": False,
    }


def _verify_feature_binding(
    store: Path, manifest: Mapping[str, Any], objects: Sequence[Any]
) -> None:
    binding_value = manifest.get("derived_feature_artifact")
    if binding_value is None:
        return
    binding = _object(binding_value, "derived feature binding")
    object_by_logical = {
        str(_object(value, "training-input object").get("logical_path")): _object(
            value, "training-input object"
        )
        for value in objects
    }
    manifest_logical = str(binding.get("manifest_logical_path", ""))
    manifest_object = object_by_logical.get(manifest_logical)
    if manifest_object is None:
        raise TrainingHandoffError("derived feature manifest object is absent")
    feature_manifest_path = _object_path(store, str(manifest_object.get("sha256", "")))
    try:
        feature_manifest = json.loads(feature_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TrainingHandoffError("derived feature manifest is invalid") from error
    feature_manifest = _object(feature_manifest, "derived feature manifest")
    for key in ("artifact_id", "feature_spec_id", "manifest_content_id", "shape", "sample_count"):
        if feature_manifest.get(key) != binding.get(key):
            raise TrainingHandoffError("derived feature binding differs from its manifest")
    source = _object(feature_manifest.get("source_dataset"), "derived feature source")
    if source != manifest.get("source_dataset"):
        raise TrainingHandoffError("derived feature source dataset drift")
    training_view = _object(feature_manifest.get("training_view"), "derived feature view")
    model_view = _object(manifest.get("model_view"), "training model view")
    if (
        training_view.get("serializer_version") != model_view.get("serializer_version")
        or training_view.get("input_profile") != model_view.get("input_profile")
        or training_view.get("qwen_identity") != model_view.get("qwen_identity")
    ):
        raise TrainingHandoffError("derived feature model-view drift")
    prefix = str(Path(manifest_logical).parent)
    for value in _sequence(feature_manifest.get("files"), "derived feature files"):
        item = _object(value, "derived feature file")
        logical_path = f"{prefix}/{item.get('path')}"
        declared = object_by_logical.get(logical_path)
        if (
            declared is None
            or declared.get("sha256") != item.get("sha256")
            or declared.get("bytes") != item.get("bytes")
        ):
            raise TrainingHandoffError("derived feature file inventory drift")


def stage_training_input(
    *, source_store: str | Path, receiver_store: str | Path, training_input_id: str
) -> dict[str, Any]:
    """Transfer only missing immutable objects and write a receiver-side receipt."""

    source = Path(source_store).expanduser().resolve()
    receiver = Path(receiver_store).expanduser().resolve()
    manifest = _load_manifest(source, training_input_id)
    transferred = 0
    transferred_bytes = 0
    reused = 0
    for value in _sequence(manifest.get("objects"), "training-input objects"):
        item = _object(value, "training-input object")
        digest = str(item.get("sha256", ""))
        source_object = _object_path(source, digest)
        if not source_object.is_file() or _sha256(source_object) != digest:
            raise TrainingHandoffError("source training-input object is missing or corrupt")
        destination = _object_path(receiver, digest)
        if destination.exists():
            if _sha256(destination) != digest:
                raise TrainingHandoffError("receiver object is corrupt; refusing overwrite")
            reused += 1
            continue
        _atomic_copy(source_object, destination)
        if _sha256(destination) != digest:
            destination.unlink(missing_ok=True)
            raise TrainingHandoffError("receiver object failed post-transfer checksum")
        transferred += 1
        transferred_bytes += destination.stat().st_size
    source_manifest = source / "manifests" / f"{training_input_id}.json"
    receiver_manifest = receiver / "manifests" / source_manifest.name
    if receiver_manifest.exists():
        if receiver_manifest.read_bytes() != source_manifest.read_bytes():
            raise TrainingHandoffError("receiver manifest collision")
    else:
        _atomic_copy(source_manifest, receiver_manifest)
    verification = verify_training_input(receiver, training_input_id)
    receipt_payload = {
        "schema": STAGING_RECEIPT_SCHEMA,
        "training_input_id": training_input_id,
        "status": verification["status"],
        "transferred_objects": transferred,
        "transferred_bytes": transferred_bytes,
        "reused_objects": reused,
        "verified_objects": verification["object_count"],
        "training_authorized": False,
    }
    receipt_id = semantic_hash(receipt_payload)
    receipt = {**receipt_payload, "receipt_id": receipt_id}
    _atomic_write(
        receiver / "receipts" / f"{receipt_id}.json", canonical_json(receipt) + "\n"
    )
    return receipt


def resolve_training_object(
    store_directory: str | Path, training_input_id: str, logical_path: str
) -> Path:
    """Resolve one verified logical artifact for a training consumer."""

    store = Path(store_directory).expanduser().resolve()
    manifest = _load_manifest(store, training_input_id)
    matches = [
        _object(item, "training-input object")
        for item in _sequence(manifest.get("objects"), "training-input objects")
        if _object(item, "training-input object").get("logical_path") == logical_path
    ]
    if len(matches) != 1:
        raise TrainingHandoffError("logical training artifact is absent or ambiguous")
    digest = str(matches[0].get("sha256", ""))
    path = _object_path(store, digest)
    if not path.is_file() or _sha256(path) != digest:
        raise TrainingHandoffError("resolved training artifact is missing or corrupt")
    return path
