"""Checksum-bound model artifact manifests with no model-loading side effects."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import canonical_json
from .contracts import ContractError


class ArtifactError(ContractError):
    """Raised when an artifact path or checksum is not trustworthy."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative_path(value: str) -> PurePosixPath:
    if "\\" in value:
        raise ArtifactError("artifact paths must use portable forward slashes")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ArtifactError(f"unsafe artifact path: {value!r}")
    return path


def _file_entry(root: Path, relative: str) -> dict[str, Any]:
    portable = _safe_relative_path(relative)
    root_resolved = root.resolve()
    source = (root / Path(*portable.parts)).resolve(strict=True)
    if not source.is_relative_to(root_resolved) or not source.is_file():
        raise ArtifactError(f"artifact file escapes its root: {relative}")
    return {"path": str(portable), "sha256": sha256_file(source), "bytes": source.stat().st_size}


def build_model_artifact_manifest(
    root: Path,
    *,
    artifact_id: str,
    source_revision: str,
    experiment_id: str,
    architecture_id: str,
    input_profile: str,
    backbone: Mapping[str, Any],
    files: Sequence[str],
    data_manifests: Sequence[Mapping[str, Any]],
    metrics: Mapping[str, Any],
    compatibility: Mapping[str, Any],
    non_claims: Sequence[str],
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic, reviewable manifest for files below ``root``."""

    required_strings = (artifact_id, source_revision, experiment_id, architecture_id, input_profile)
    if any(not value.strip() for value in required_strings):
        raise ArtifactError("artifact identity fields must be non-empty")
    if not files or len(set(files)) != len(files):
        raise ArtifactError("artifact files must be a non-empty unique list")
    if not non_claims or any(not value.strip() for value in non_claims):
        raise ArtifactError("artifact non-claims must be explicit")
    return {
        "schema": "stpd/model-artifact-manifest-v0",
        "artifact_id": artifact_id,
        "created_at": created_at or datetime.now(UTC).replace(microsecond=0).isoformat(),
        "source_revision": source_revision,
        "experiment_id": experiment_id,
        "architecture_id": architecture_id,
        "input_profile": input_profile,
        "backbone": dict(backbone),
        "files": [_file_entry(root, value) for value in files],
        "data_manifests": [dict(value) for value in data_manifests],
        "metrics": dict(metrics),
        "compatibility": dict(compatibility),
        "non_claims": list(non_claims),
    }


def write_model_artifact_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")


def verify_model_artifact_manifest(root: Path, manifest: Mapping[str, Any] | Path) -> None:
    """Verify every named file without importing or loading model code."""

    value = (
        json.loads(manifest.read_text(encoding="utf-8"))
        if isinstance(manifest, Path)
        else dict(manifest)
    )
    if value.get("schema") != "stpd/model-artifact-manifest-v0":
        raise ArtifactError("unsupported model artifact manifest")
    entries = value.get("files")
    if not isinstance(entries, list) or not entries:
        raise ArtifactError("model artifact manifest has no files")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ArtifactError("artifact file entry is not an object")
        relative = str(entry.get("path", ""))
        if relative in seen:
            raise ArtifactError(f"duplicate artifact file: {relative}")
        seen.add(relative)
        actual = _file_entry(root, relative)
        if actual["sha256"] != entry.get("sha256") or actual["bytes"] != entry.get("bytes"):
            raise ArtifactError(f"artifact checksum mismatch: {relative}")

