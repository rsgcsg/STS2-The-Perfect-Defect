"""Pinned full-weight Qwen L2 acquisition and offline identity verification."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias, cast

from .l1 import (
    ALLOWLISTED_FILES,
    PinnedFile,
    QwenL1Error,
    QwenL1Pin,
    extract_special_tokens,
    is_weight_file,
    load_pin,
    sha256_file,
    special_tokens_sha256,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_L2_PIN_PATH = ROOT / "configs" / "v0" / "qwen" / "qwen3-0.6b-base-l2.json"
L2_MANIFEST_SCHEMA = "stpd/qwen-l2-artifact-v0"


class QwenL2Error(QwenL1Error):
    """Raised when the full-weight L2 snapshot or admission contract fails."""


@dataclass(frozen=True)
class L2WeightFile:
    name: str
    size_bytes: int
    sha256: str
    kind: str = "weights"

    def validate(self) -> None:
        if not is_weight_file(self.name) or Path(self.name).name != self.name:
            raise QwenL2Error(f"invalid L2 weight filename: {self.name}")
        if self.size_bytes <= 0:
            raise QwenL2Error(f"weight file size must be positive: {self.name}")
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise QwenL2Error(f"invalid weight SHA-256: {self.name}")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "name": self.name,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


L2File: TypeAlias = PinnedFile | L2WeightFile


@dataclass(frozen=True)
class QwenL2BackendConfig:
    architecture: str
    hidden_state_layer: int
    pooling: str
    joint_format: str
    add_special_tokens: bool
    silent_truncation: bool
    use_cache: bool
    attention_implementation: str
    dtype: str

    def validate(self) -> None:
        expected = {
            "architecture": "Qwen3ForCausalLM",
            "hidden_state_layer": -1,
            "pooling": "masked-mean-v0",
            "joint_format": "state-newline-action-v0",
            "add_special_tokens": False,
            "silent_truncation": False,
            "use_cache": False,
            "attention_implementation": "eager",
            "dtype": "bfloat16",
        }
        actual = self.__dict__
        for key, value in expected.items():
            if actual[key] != value:
                raise QwenL2Error(
                    f"unsupported L2 backend {key}: expected {value!r}, got {actual[key]!r}"
                )


@dataclass(frozen=True)
class QwenL2Pin:
    l1: QwenL1Pin
    weight_files: tuple[L2WeightFile, ...]
    backend: QwenL2BackendConfig

    @property
    def model_id(self) -> str:
        return self.l1.model_id

    @property
    def repo_revision(self) -> str:
        return self.l1.repo_revision

    @property
    def expected_files(self) -> tuple[L2File, ...]:
        return self.l1.files + self.weight_files

    @property
    def weights_sha256(self) -> str:
        digest = hashlib.sha256()
        for file in self.weight_files:
            digest.update(file.name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(file.sha256.encode("ascii"))
            digest.update(b"\0")
        return digest.hexdigest()

    def validate(self) -> None:
        self.l1.validate()
        self.backend.validate()
        if not self.weight_files:
            raise QwenL2Error("L2 pin must contain at least one weight file")
        names: set[str] = set()
        for file in self.weight_files:
            file.validate()
            if not is_weight_file(file.name):
                raise QwenL2Error(f"L2 weight entry is not a recognized weight file: {file.name}")
            if file.name in names or file.name in ALLOWLISTED_FILES:
                raise QwenL2Error(f"duplicate L2 file pin: {file.name}")
            names.add(file.name)


@dataclass(frozen=True)
class QwenL2Artifact:
    model_id: str
    repo_revision: str
    files: tuple[L2File, ...]
    config_sha256: str
    tokenizer_bundle_sha256: str
    special_tokens_sha256: str
    weights_sha256: str

    @property
    def snapshot_sha256(self) -> str:
        value = [
            {"name": file.name, "sha256": file.sha256, "size_bytes": file.size_bytes}
            for file in self.files
        ]
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": L2_MANIFEST_SCHEMA,
            "model_id": self.model_id,
            "repo_revision": self.repo_revision,
            "cache_mode": "full_weight_local_snapshot",
            "files": [file.to_dict() for file in self.files],
            "config_sha256": self.config_sha256,
            "tokenizer_bundle_sha256": self.tokenizer_bundle_sha256,
            "special_tokens_sha256": self.special_tokens_sha256,
            "weights_sha256": self.weights_sha256,
            "snapshot_sha256": self.snapshot_sha256,
        }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QwenL2Error(f"cannot read Qwen L2 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise QwenL2Error(f"Qwen L2 JSON must be an object: {path}")
    return cast(dict[str, Any], value)


def load_l2_pin(path: Path | None = None) -> QwenL2Pin:
    """Load the checked-in full-weight pin and its immutable L1 dependency."""

    pin_path = (path or DEFAULT_L2_PIN_PATH).resolve()
    value = _load_json(pin_path)
    try:
        l1_name = str(value["l1_pin"])
        l1_path = (pin_path.parent / l1_name).resolve()
        if l1_path.parent != pin_path.parent:
            raise QwenL2Error("L2 l1_pin must stay in the same config directory")
        l1 = load_pin(l1_path)
        if value["model_id"] != l1.model_id or value["repo_revision"] != l1.repo_revision:
            raise QwenL2Error("L1 and L2 model/revision identities disagree")
        weights = tuple(
            L2WeightFile(
                name=str(entry["name"]),
                size_bytes=int(entry["size_bytes"]),
                sha256=str(entry["sha256"]),
            )
            for entry in value["weight_files"]
        )
        backend_value = cast(Mapping[str, Any], value["backend"])
        backend = QwenL2BackendConfig(
            architecture=str(backend_value["architecture"]),
            hidden_state_layer=int(backend_value["hidden_state_layer"]),
            pooling=str(backend_value["pooling"]),
            joint_format=str(backend_value["joint_format"]),
            add_special_tokens=bool(backend_value["add_special_tokens"]),
            silent_truncation=bool(backend_value["silent_truncation"]),
            use_cache=bool(backend_value["use_cache"]),
            attention_implementation=str(backend_value["attention_implementation"]),
            dtype=str(backend_value["dtype"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise QwenL2Error(f"invalid Qwen L2 pin: {pin_path}") from exc
    pin = QwenL2Pin(l1=l1, weight_files=weights, backend=backend)
    pin.validate()
    return pin


def l2_snapshot_path(cache_dir: Path, pin: QwenL2Pin | None = None) -> Path:
    resolved = pin or load_l2_pin()
    safe_model_id = resolved.model_id.replace("/", "--")
    return (
        cache_dir.expanduser()
        / f"models--{safe_model_id}"
        / "snapshots"
        / resolved.repo_revision
    )


def inspect_l2_snapshot(snapshot: Path, pin: QwenL2Pin | None = None) -> QwenL2Artifact:
    """Hash and validate every file in a local full-weight snapshot without network access."""

    resolved = pin or load_l2_pin()
    resolved.validate()
    snapshot = snapshot.expanduser().resolve()
    if not snapshot.is_dir():
        raise QwenL2Error(f"L2 snapshot does not exist: {snapshot}")
    paths = {
        path.relative_to(snapshot).as_posix(): path
        for path in snapshot.rglob("*")
        if path.is_file()
    }
    expected = {file.name: file for file in resolved.expected_files}
    missing = sorted(set(expected) - set(paths))
    unexpected = sorted(set(paths) - set(expected))
    if missing:
        raise QwenL2Error("missing pinned L2 files: " + ", ".join(missing))
    if unexpected:
        raise QwenL2Error("unexpected files in L2 snapshot: " + ", ".join(unexpected))

    actual: list[L2File] = []
    for expected_file in resolved.expected_files:
        path = paths[expected_file.name]
        size = path.stat().st_size
        digest = sha256_file(path)
        if size != expected_file.size_bytes or digest != expected_file.sha256:
            raise QwenL2Error(
                f"content pin failed for {expected_file.name}: expected "
                f"{expected_file.size_bytes}/{expected_file.sha256}, got {size}/{digest}"
            )
        if expected_file.kind == "weights":
            actual.append(L2WeightFile(expected_file.name, size, digest))
        else:
            actual.append(PinnedFile(expected_file.name, expected_file.kind, size, digest))

    config = _load_json(snapshot / "config.json")
    for key, expected_value in resolved.l1.config_expectations.items():
        if config.get(key) != expected_value:
            raise QwenL2Error(
                f"config expectation failed for {key}: expected {expected_value!r}, "
                f"got {config.get(key)!r}"
            )
    tokens = extract_special_tokens(snapshot)
    if tokens != resolved.l1.special_tokens:
        raise QwenL2Error("L2 special-token entries do not match the L1 pin")
    token_digest = special_tokens_sha256(tokens)
    if token_digest != resolved.l1.special_tokens_sha256:
        raise QwenL2Error("L2 special-token digest does not match the L1 pin")
    return QwenL2Artifact(
        model_id=resolved.model_id,
        repo_revision=resolved.repo_revision,
        files=tuple(actual),
        config_sha256=resolved.l1.config_sha256,
        tokenizer_bundle_sha256=resolved.l1.tokenizer_bundle_sha256,
        special_tokens_sha256=token_digest,
        weights_sha256=resolved.weights_sha256,
    )


def inspect_l2_cache(cache_dir: Path, pin: QwenL2Pin | None = None) -> QwenL2Artifact:
    resolved = pin or load_l2_pin()
    return inspect_l2_snapshot(l2_snapshot_path(cache_dir, resolved), resolved)


def _manifest_path(cache_dir: Path, pin: QwenL2Pin) -> Path:
    safe_model_id = pin.model_id.replace("/", "--")
    return cache_dir.expanduser() / "manifests" / f"{safe_model_id}-{pin.repo_revision}-l2.json"


def fetch_l2_snapshot(
    cache_dir: Path,
    pin: QwenL2Pin | None = None,
    *,
    token: str | None = None,
) -> QwenL2Artifact:
    """Download only the exact pinned config/tokenizer/weight payload, then hash it offline."""

    resolved = pin or load_l2_pin()
    resolved.validate()
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise QwenL2Error("Qwen L2 fetch requires the optional L2 dependencies") from exc
    snapshot_download(
        repo_id=resolved.model_id,
        revision=resolved.repo_revision,
        cache_dir=str(cache_dir.expanduser()),
        allow_patterns=[file.name for file in resolved.expected_files],
        token=token,
    )
    artifact = inspect_l2_cache(cache_dir, resolved)
    manifest = _manifest_path(cache_dir, resolved)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(artifact.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact


def discover_l2_pin(
    pin: QwenL2Pin | None = None,
    *,
    token: str | None = None,
) -> dict[str, Any]:
    """Verify the pinned Hub revision and LFS metadata without downloading the weight."""

    resolved = pin or load_l2_pin()
    try:
        from huggingface_hub import HfApi
    except ImportError as exc:
        raise QwenL2Error("Qwen L2 discovery requires the optional L2 dependencies") from exc
    info = HfApi(token=token).model_info(
        resolved.model_id,
        revision=resolved.repo_revision,
        files_metadata=True,
    )
    if info.sha != resolved.repo_revision:
        raise QwenL2Error("Hub did not resolve the exact pinned Qwen revision")
    siblings = {str(item.rfilename): item for item in info.siblings or ()}
    observations: list[dict[str, Any]] = []
    for expected in resolved.weight_files:
        sibling = siblings.get(expected.name)
        if sibling is None:
            raise QwenL2Error(f"Hub revision is missing pinned weight: {expected.name}")
        lfs = getattr(sibling, "lfs", None)
        if isinstance(lfs, Mapping):
            remote_sha = lfs.get("sha256")
            remote_size = lfs.get("size")
        else:
            remote_sha = getattr(lfs, "sha256", None)
            remote_size = getattr(lfs, "size", None)
        if remote_sha != expected.sha256 or remote_size != expected.size_bytes:
            raise QwenL2Error(
                f"Hub LFS identity mismatch for {expected.name}: "
                f"expected {expected.size_bytes}/{expected.sha256}, got {remote_size}/{remote_sha}"
            )
        observations.append(
            {"name": expected.name, "size_bytes": remote_size, "sha256": remote_sha}
        )
    return {
        "schema": "stpd/qwen-l2-discovery-v0",
        "model_id": resolved.model_id,
        "repo_revision": resolved.repo_revision,
        "weights": observations,
        "matches_pin": True,
    }


def default_l2_cache() -> Path:
    return Path(os.environ.get("STPD_QWEN_L2_CACHE", "~/.cache/stpd/qwen-l2")).expanduser()


def expected_file_names(pin: QwenL2Pin | None = None) -> Sequence[str]:
    return tuple(file.name for file in (pin or load_l2_pin()).expected_files)
