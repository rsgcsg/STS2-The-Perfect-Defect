"""Decision-only adapter over the resident S1 model.

This module deliberately stops at scoring a complete candidate catalog. It does not
execute an action or retain any environment lifecycle state.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, cast

from ..canonical import canonical_json
from .s1 import (
    DEFAULT_CONFIG,
    ResidentS1Model,
    S1PolicyError,
    admit_snapshot,
    checkpoint_model_reads,
    load_resident_s1,
    validate_model_read_policy,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "policy-manifests" / "s1-policy-adapter-v1.json"
MANIFEST_SCHEMA = "sts2.policy-runtime/policy-manifest-1"
PORT_SCHEMA = "sts2.policy-runtime/policy-port-1"
ADAPTER_PROTOCOL = "sts2.policy-runtime/decision-only-ndjson-1"
ADAPTER_CODE_PATHS = (
    Path(__file__).resolve(),
    Path(__file__).with_name("s1.py").resolve(),
    (ROOT / "tools" / "policy_adapter.py").resolve(),
)


class PolicyAdapterError(RuntimeError):
    """A malformed request or an unavailable decision-only policy."""


class ResidentModel(Protocol):
    def project_and_score(
        self,
        snapshot: Mapping[str, Any],
        reads: Mapping[str, Mapping[str, Any]],
        *,
        game_version: str,
        game_commit: str,
    ) -> tuple[Any, list[str], list[float], float]: ...


ModelLoader = Callable[[Path], tuple[ResidentS1Model, dict[str, Any]]]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def adapter_code_sha256() -> str:
    """Digest the bounded decision-adapter implementation, excluding model artifacts."""

    files = [
        {"path": path.relative_to(ROOT).as_posix(), "sha256": _sha256(path)}
        for path in ADAPTER_CODE_PATHS
    ]
    return hashlib.sha256(canonical_json(files).encode("utf-8")).hexdigest()


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PolicyAdapterError(f"{name} must be an object")
    return dict(value)


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyAdapterError(f"cannot read policy manifest: {path}") from exc
    return _object(value, "policy manifest")


def _relative_to_root(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _support(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return _object(manifest.get("support"), "manifest.support")


def _s1_config(manifest: Mapping[str, Any]) -> dict[str, Any]:
    adapter_config = _object(manifest.get("adapter_config"), "manifest.adapter_config")
    return _object(adapter_config.get("s1"), "manifest.adapter_config.s1")


def _validate_manifest_config(
    manifest: Mapping[str, Any], config_path: Path, config: Mapping[str, Any]
) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise PolicyAdapterError("unsupported policy manifest schema")
    adapter = _object(manifest.get("adapter"), "manifest.adapter")
    if adapter.get("protocol") != ADAPTER_PROTOCOL:
        raise PolicyAdapterError("policy manifest protocol drift")
    expected_code_sha256 = adapter.get("code_sha256")
    if expected_code_sha256 != adapter_code_sha256():
        raise PolicyAdapterError("policy manifest adapter code checksum drift")
    config_pin = _object(_s1_config(manifest).get("config"), "manifest.adapter_config.s1.config")
    expected_path = config_pin.get("path")
    expected_sha = config_pin.get("sha256")
    if not isinstance(expected_path, str) or not isinstance(expected_sha, str):
        raise PolicyAdapterError("policy manifest must pin the S1 config")
    if expected_path != _relative_to_root(config_path):
        raise PolicyAdapterError("policy manifest S1 config path drift")
    if not config_path.is_file() or _sha256(config_path) != expected_sha:
        raise PolicyAdapterError("policy manifest S1 config checksum drift")
    if config.get("schema") != config_pin.get("schema"):
        raise PolicyAdapterError("policy manifest S1 config schema drift")


def _validate_loaded_model(manifest: Mapping[str, Any], model: ResidentModel) -> None:
    artifact = _object(manifest.get("artifact"), "manifest.artifact")
    actual_checkpoint = getattr(model, "checkpoint_sha256", None)
    if artifact.get("sha256") != actual_checkpoint:
        raise PolicyAdapterError("loaded S1 checkpoint differs from policy manifest")

    identity = getattr(model, "identity", None)
    if identity is None:
        raise PolicyAdapterError("resident S1 identity is absent")
    s1 = _s1_config(manifest)
    serializer = _object(s1.get("serializer"), "manifest.adapter_config.s1.serializer")
    if serializer.get("version") != getattr(identity, "serializer_version", None):
        raise PolicyAdapterError("loaded serializer differs from policy manifest")
    if serializer.get("input_profile") != getattr(identity, "input_profile", None):
        raise PolicyAdapterError("loaded input profile differs from policy manifest")

    qwen_pin = _object(s1.get("qwen"), "manifest.adapter_config.s1.qwen")
    qwen = getattr(identity, "qwen", None)
    if qwen is None:
        raise PolicyAdapterError("resident Qwen identity is absent")
    for field in ("model_id", "model_revision", "control"):
        if qwen_pin.get(field) != getattr(qwen, field, None):
            raise PolicyAdapterError(f"loaded Qwen {field} differs from policy manifest")


def _candidate_count(snapshot: Mapping[str, Any]) -> int:
    catalog = snapshot.get("bound_actions")
    if not isinstance(catalog, Mapping):
        raise PolicyAdapterError("snapshot bound_actions catalog is missing")
    actions = catalog.get("actions")
    if not isinstance(actions, list) or not actions:
        raise PolicyAdapterError("snapshot requires a non-empty candidate catalog")
    count = len(actions)
    if (
        catalog.get("status") != "complete"
        or catalog.get("materialized_count") != count
        or catalog.get("total_count") != count
    ):
        raise PolicyAdapterError("snapshot candidate catalog is not complete")
    return count


def _bound_action_order_digest(snapshot: Mapping[str, Any]) -> str:
    catalog = _object(snapshot.get("bound_actions"), "snapshot.bound_actions")
    actions = catalog.get("actions")
    if not isinstance(actions, list):
        raise PolicyAdapterError("snapshot bound action catalog is missing")
    identities: list[str] = []
    for action_value in actions:
        action = _object(action_value, "snapshot bound action")
        identity = action.get("bound_action_id")
        if not isinstance(identity, str) or not identity:
            raise PolicyAdapterError("snapshot bound action identity is missing")
        identities.append(identity)
    if len(identities) != len(set(identities)):
        raise PolicyAdapterError("snapshot bound action identities are not unique")
    return hashlib.sha256(canonical_json(identities).encode("utf-8")).hexdigest()


def _validate_projected_action_order(snapshot: Mapping[str, Any], decision: Any) -> None:
    """Prove model score index and Connector BoundAction index name the same action."""

    catalog = _object(snapshot.get("bound_actions"), "snapshot.bound_actions")
    actions = catalog.get("actions")
    envelopes = getattr(decision, "envelopes", None)
    if not isinstance(actions, list) or not isinstance(envelopes, Sequence):
        raise PolicyAdapterError("resident S1 execution envelope order is missing")
    expected = [
        _object(action, "snapshot bound action").get("bound_action_id") for action in actions
    ]
    actual = [getattr(envelope, "bound_action_id", None) for envelope in envelopes]
    if actual != expected:
        raise PolicyAdapterError("resident S1 reordered the Connector candidate catalog")


class PolicyAdapter:
    """Load one resident S1 model and expose only complete-catalog decisions."""

    def __init__(
        self,
        *,
        config_path: Path = DEFAULT_CONFIG,
        manifest_path: Path = DEFAULT_MANIFEST,
        model_loader: ModelLoader = load_resident_s1,
        manifest: Mapping[str, Any] | None = None,
    ) -> None:
        self.config_path = config_path.expanduser().resolve()
        self.manifest_path = manifest_path.expanduser().resolve()
        self._model_loader = model_loader
        self._manifest_override = dict(manifest) if manifest is not None else None
        self._manifest: dict[str, Any] | None = None
        self._model: ResidentModel | None = None
        self._config: dict[str, Any] | None = None
        self._closed = False

    @property
    def manifest(self) -> Mapping[str, Any]:
        if self._manifest is None:
            raise PolicyAdapterError("policy adapter is not initialized")
        return self._manifest

    def initialize(self) -> dict[str, Any]:
        if self._closed:
            raise PolicyAdapterError("policy adapter is closed")
        if self._model is not None:
            raise PolicyAdapterError("policy adapter is already initialized")
        manifest = (
            self._manifest_override
            if self._manifest_override is not None
            else _read_manifest(self.manifest_path)
        )
        model, config = self._model_loader(self.config_path)
        _validate_manifest_config(manifest, self.config_path, config)
        _validate_loaded_model(manifest, model)
        self._manifest = dict(manifest)
        self._model = model
        self._config = config
        return {
            "ok": True,
            "op": "initialize",
            "protocol": PORT_SCHEMA,
            "manifest": self._manifest,
        }

    def decide(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if self._closed:
            raise PolicyAdapterError("policy adapter is closed")
        if self._model is None or self._config is None:
            raise PolicyAdapterError("policy adapter is not initialized")
        request_manifest = _object(request.get("manifest"), "decide.manifest")
        if canonical_json(request_manifest) != canonical_json(self.manifest):
            raise PolicyAdapterError("decide policy manifest differs from loaded manifest")
        bundle = _object(request.get("bundle"), "decide.bundle")
        snapshot = _object(bundle.get("observation"), "decide.bundle.observation")
        reads_raw = bundle.get("reads", [])
        if not isinstance(reads_raw, list):
            raise PolicyAdapterError("decide.bundle.reads must be an array")
        reads: dict[str, dict[str, Any]] = {}
        for value in reads_raw:
            read = _object(value, "decide.bundle.read")
            read_id = read.get("read_id")
            if not isinstance(read_id, str) or not read_id or read_id in reads:
                raise PolicyAdapterError("decide.bundle.reads require unique read_id values")
            reads[read_id] = read
        candidate_count = _candidate_count(snapshot)
        candidate_digest = _bound_action_order_digest(snapshot)
        if request.get("candidate_digest") != candidate_digest:
            raise PolicyAdapterError("decide candidate order digest mismatch")
        if request.get("candidate_count") != candidate_count:
            raise PolicyAdapterError("decide candidate count mismatch")
        support = _support(self.manifest)
        game_versions = support.get("game_versions")
        game_commits = support.get("game_commits")
        if not isinstance(game_versions, list) or len(game_versions) != 1:
            raise PolicyAdapterError("S1 adapter requires one exact supported game version")
        if not isinstance(game_commits, list) or len(game_commits) != 1:
            raise PolicyAdapterError("S1 adapter requires one exact supported game commit")
        game_version = game_versions[0]
        game_commit = game_commits[0]

        admission = admit_snapshot(snapshot)
        if not admission.available:
            raise PolicyAdapterError(
                f"S1 policy does not support this whole decision: {admission.reason}"
            )
        try:
            model_read_policy = validate_model_read_policy(self._config.get("model_read_policy"))
            model_reads = checkpoint_model_reads(tuple(reads.values()), model_read_policy)
        except S1PolicyError as exc:
            raise PolicyAdapterError(str(exc)) from exc

        try:
            decision, action_texts, scores, _latency_ms = self._model.project_and_score(
                snapshot,
                cast(Mapping[str, Mapping[str, Any]], model_reads),
                game_version=game_version,
                game_commit=game_commit,
            )
        except S1PolicyError as exc:
            raise PolicyAdapterError(str(exc)) from exc
        actions = getattr(decision, "actions", None)
        if (
            not isinstance(actions, Sequence)
            or isinstance(actions, (str, bytes, bytearray))
            or len(actions) != candidate_count
            or len(action_texts) != candidate_count
            or len(scores) != candidate_count
        ):
            raise PolicyAdapterError("resident S1 changed the complete candidate count")
        if not scores or not all(isinstance(score, (int, float)) for score in scores):
            raise PolicyAdapterError("resident S1 returned invalid candidate scores")
        selected_index = max(range(len(scores)), key=scores.__getitem__)
        _validate_projected_action_order(snapshot, decision)
        return {
            "candidate_digest": candidate_digest,
            "scores": [float(score) for score in scores],
            "selected_index": selected_index,
        }

    def close(self) -> dict[str, Any]:
        self._model = None
        self._config = None
        self._closed = True
        return {"ok": True, "op": "close"}


def _error_response(request_id: str, exc: Exception) -> dict[str, Any]:
    return {
        "schema": PORT_SCHEMA,
        "message_type": "error",
        "request_id": request_id,
        "error": {"code": "policy_error", "message": str(exc)},
    }


def _handle_request(adapter: PolicyAdapter, request: Mapping[str, Any]) -> dict[str, Any]:
    if set(request) != {"schema", "message_type", "request_id", "input"}:
        raise PolicyAdapterError("policy port request has unknown or missing fields")
    if request.get("schema") != PORT_SCHEMA or request.get("message_type") != "decide":
        raise PolicyAdapterError("unsupported policy port request")
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise PolicyAdapterError("policy port request_id must be a non-empty string")
    decision_input = _object(request.get("input"), "policy port input")
    if set(decision_input) != {
        "run_id",
        "manifest",
        "bundle",
        "candidate_digest",
        "candidate_count",
    }:
        raise PolicyAdapterError("policy port input has unknown or missing fields")
    if not isinstance(decision_input.get("run_id"), str) or not decision_input["run_id"]:
        raise PolicyAdapterError("policy port run_id must be a non-empty string")
    output = adapter.decide(decision_input)
    return {
        "schema": PORT_SCHEMA,
        "message_type": "decision",
        "request_id": request_id,
        "output": output,
    }


def serve_ndjson(
    adapter: PolicyAdapter,
    *,
    input_lines: Iterator[str] | None = None,
    output: Any = None,
) -> int:
    """Run the Platform decision-only protocol until EOF."""

    source = input_lines if input_lines is not None else iter(sys.stdin)
    destination = output if output is not None else sys.stdout
    adapter.initialize()
    for line in source:
        if not line.strip():
            continue
        request: object = None
        try:
            request = json.loads(line)
            if not isinstance(request, Mapping):
                raise PolicyAdapterError("NDJSON request must be an object")
            response = _handle_request(adapter, request)
        except (PolicyAdapterError, ValueError, TypeError, json.JSONDecodeError) as exc:
            request_id = "unknown"
            if isinstance(request, Mapping):
                candidate_request_id = request.get("request_id")
                if isinstance(candidate_request_id, str):
                    request_id = candidate_request_id
            response = _error_response(request_id, exc)
        destination.write(canonical_json(response) + "\n")
        destination.flush()
    adapter.close()
    return 0
