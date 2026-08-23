"""Exact S1 checkpoint inference behind Connector-owned live authority."""

from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import torch

from ..canonical import canonical_json
from ..contracts import QwenIdentity, ensure_score_alignment
from ..environment.projector import ProjectedDecision, ResearchProjectorV0
from ..models import Scheme1Scorer
from ..qwen.l2 import inspect_l2_cache, l2_snapshot_path, load_l2_pin
from ..qwen.real_backend import CachingQwenBackend, RealQwenBackend
from ..representation import InputProfile, model_serializer
from ..training import CheckpointIdentity, CheckpointManager, TrainerState

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs" / "v0" / "experiments" / "s1-human-combat-live-v1.json"
SUPPORTED_VERBS = frozenset({"play", "end_turn"})
SUPPORTED_ACTION_KINDS = frozenset({"play_card", "end_turn"})
HUMAN_CHECKPOINT_MODEL_READ_POLICY = {
    "mode": "none",
    "training_basis": "human_annotator_importer_empty_reads",
    "standard_reads_line_expected": False,
}


class LiveS1Error(RuntimeError):
    """A classified live boundary failure; never permission to guess or retry."""


class StaleObservationError(LiveS1Error):
    """One Snapshot+Reads transaction raced with a newer Connector snapshot."""


def validate_model_read_policy(value: Any) -> dict[str, Any]:
    """Pin live projection to the exact Read semantics used by the Human checkpoint."""

    if not isinstance(value, Mapping) or dict(value) != HUMAN_CHECKPOINT_MODEL_READ_POLICY:
        raise LiveS1Error(
            "live model Read policy differs from Human checkpoint training semantics"
        )
    return dict(HUMAN_CHECKPOINT_MODEL_READ_POLICY)


def canonicalize_prefetched_reads(reads: Any) -> tuple[dict[str, Any], ...]:
    """Retain every SDK Read instance and order only by its opaque unique identity."""

    if not isinstance(reads, Sequence) or isinstance(reads, (str, bytes, bytearray)):
        raise LiveS1Error("Connector SDK decision-bundle Reads must be an array")
    identities: set[str] = set()
    result: list[dict[str, Any]] = []
    for read_raw in reads:
        if not isinstance(read_raw, Mapping):
            raise LiveS1Error("Connector SDK decision-bundle Read must be an object")
        read = dict(read_raw)
        read_id = read.get("read_id")
        if not isinstance(read_id, str) or not read_id:
            raise LiveS1Error("Connector SDK decision-bundle Read identity is missing")
        if read_id in identities:
            raise LiveS1Error(f"duplicate Connector Read identity is unsupported: {read_id}")
        identities.add(read_id)
        result.append(read)
    return tuple(sorted(result, key=lambda read: str(read["read_id"])))


def checkpoint_model_reads(
    prefetched_reads: Sequence[Mapping[str, Any]],
    model_read_policy: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    """Return the exact mapping passed to ResearchProjectorV0 during training import."""

    validate_model_read_policy(model_read_policy)
    if prefetched_reads:
        raise LiveS1Error("none Read policy received unexpected prefetched Read responses")
    return {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LiveS1Error(f"JSON root must be an object: {path}")
    return cast(dict[str, Any], value)


def _qwen_identity(value: Mapping[str, Any]) -> QwenIdentity:
    fields = QwenIdentity.__dataclass_fields__
    if set(value) != set(fields):
        raise LiveS1Error("checkpoint Qwen identity fields drifted")
    identity = QwenIdentity(**{name: value[name] for name in fields})
    identity.validate_scientific_v0()
    return identity


@dataclass(frozen=True)
class SnapshotAdmission:
    available: bool
    reason: str
    interaction: str
    surface: str
    legal_action_count: int


def admit_snapshot(snapshot: Mapping[str, Any]) -> SnapshotAdmission:
    """Admit only a complete Defect A0 ordinary combat catalog as one whole set."""

    interaction_raw = snapshot.get("interaction")
    interaction = interaction_raw if isinstance(interaction_raw, Mapping) else {}
    kind = str(interaction.get("kind", "none"))
    content = interaction.get("content") if isinstance(interaction, Mapping) else None
    surface_raw = content.get("surface") if isinstance(content, Mapping) else None
    surface = str(surface_raw.get("kind", kind) if isinstance(surface_raw, Mapping) else kind)
    catalog_raw = snapshot.get("bound_actions")
    catalog = catalog_raw if isinstance(catalog_raw, Mapping) else {}
    actions_raw = catalog.get("actions")
    actions = actions_raw if isinstance(actions_raw, list) else []
    count = len(actions)
    persistent_raw = snapshot.get("persistent")
    persistent = persistent_raw if isinstance(persistent_raw, Mapping) else None
    persistent_content = persistent.get("content") if persistent else None
    if not isinstance(persistent_content, Mapping):
        return SnapshotAdmission(False, "WAITING_FOR_SUPPORTED_COMBAT", kind, surface, count)
    player = persistent_content.get("player")
    run = persistent_content.get("run")
    if not isinstance(player, Mapping) or not isinstance(run, Mapping):
        return SnapshotAdmission(False, "INCOMPLETE_PERSISTENT_RUN", kind, surface, count)
    if player.get("character_definition_id") != "DEFECT":
        return SnapshotAdmission(False, "REQUIRES_DEFECT", kind, surface, count)
    if run.get("ascension") != 0:
        return SnapshotAdmission(False, "REQUIRES_ASCENSION_0", kind, surface, count)
    if snapshot.get("status") != "interactive":
        return SnapshotAdmission(
            False, f"SNAPSHOT_{snapshot.get('status', 'UNKNOWN')}", kind, surface, count
        )
    completeness = snapshot.get("completeness")
    if not isinstance(completeness, Mapping) or completeness.get("status") != "complete":
        return SnapshotAdmission(False, "SNAPSHOT_INCOMPLETE", kind, surface, count)
    if kind != "combat_turn" or surface != "combat_turn":
        return SnapshotAdmission(False, f"NON_COMBAT_SURFACE:{kind}", kind, surface, count)
    context = content.get("context") if isinstance(content, Mapping) else None
    if not isinstance(context, Mapping) or context.get("kind") != "combat":
        return SnapshotAdmission(False, "NON_COMBAT_CONTEXT", kind, surface, count)
    if context.get("turn_owner") != "player" or context.get("is_play_phase") is not True:
        return SnapshotAdmission(False, "NOT_PLAYER_PLAY_PHASE", kind, surface, count)
    if (
        catalog.get("status") != "complete"
        or catalog.get("materialized_count") != catalog.get("total_count")
        or catalog.get("materialized_count") != count
        or count == 0
    ):
        return SnapshotAdmission(False, "LEGAL_CATALOG_INCOMPLETE", kind, surface, count)
    verbs = {str(action.get("verb")) for action in actions if isinstance(action, Mapping)}
    capability_verbs = {
        str(capability.get("verb"))
        for capability in interaction.get("capabilities", [])
        if isinstance(capability, Mapping)
    }
    if len(verbs) == 0 or not verbs.issubset(SUPPORTED_VERBS):
        return SnapshotAdmission(
            False, f"UNSUPPORTED_ACTION_CATALOG:{','.join(sorted(verbs - SUPPORTED_VERBS))}",
            kind, surface, count
        )
    if not capability_verbs.issubset(SUPPORTED_VERBS):
        return SnapshotAdmission(
            False,
            f"UNSUPPORTED_ACTION_CAPABILITY:{','.join(sorted(capability_verbs - SUPPORTED_VERBS))}",
            kind,
            surface,
            count,
        )
    return SnapshotAdmission(True, "SUPPORTED_COMBAT", kind, surface, count)


def validate_capabilities(
    capabilities: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    """Bind one live process to the exact game, Connector, protocol, and Modset."""

    host_raw = capabilities.get("host")
    game_raw = capabilities.get("game")
    host = host_raw if isinstance(host_raw, Mapping) else {}
    game = game_raw if isinstance(game_raw, Mapping) else {}
    implementation_raw = host.get("implementation")
    implementation = implementation_raw if isinstance(implementation_raw, Mapping) else {}
    modset_raw = game.get("modset")
    modset = modset_raw if isinstance(modset_raw, Mapping) else {}
    checks = {
        "protocol_version": capabilities.get("protocol_version"),
        "host_kind": host.get("host_kind"),
        "connector_source_revision": implementation.get("source_revision"),
        "connector_artifact_sha256": implementation.get("artifact_sha256"),
        "connector_artifact_mvid": implementation.get("module_version_id"),
        "game_version": game.get("version"),
        "game_commit": game.get("commit"),
        "modset_status": modset.get("status"),
        "modset_fingerprint": modset.get("fingerprint"),
    }
    for name, actual in checks.items():
        if actual != expected.get(name):
            raise LiveS1Error(
                f"live capability {name} drift: expected {expected.get(name)!r}, got {actual!r}"
            )
    loaded_mod_ids = modset.get("loaded_mod_ids")
    if loaded_mod_ids != expected.get("loaded_mod_ids"):
        raise LiveS1Error(
            "live capability loaded_mod_ids drift: "
            f"expected {expected.get('loaded_mod_ids')!r}, got {loaded_mod_ids!r}"
        )
    if capabilities.get("execution_available") is not True:
        raise LiveS1Error("Connector mutation authority is unavailable")
    if capabilities.get("single_controller") is not True:
        raise LiveS1Error("Connector does not declare single-controller authority")
    if not isinstance(host.get("runtime_instance_id"), str) or not host.get(
        "runtime_instance_id"
    ):
        raise LiveS1Error("Connector runtime instance identity is absent")


class ConnectorSdkBridge:
    """Synchronous Python client for the strategy-free official TypeScript SDK bridge."""

    def __init__(
        self,
        *,
        node: Path,
        bridge_script: Path,
        sdk: Path,
        endpoint: str,
        request_timeout_seconds: float = 15.0,
    ) -> None:
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr: list[str] = []
        self._sequence = 0
        self._closed = False
        self._timeout = request_timeout_seconds
        self._process = subprocess.Popen(
            [
                str(node),
                str(bridge_script),
                "--sdk",
                str(sdk),
                "--endpoint",
                endpoint,
                "--timeout-ms",
                str(int(request_timeout_seconds * 1000)),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.request("ping")

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    self._responses.put(cast(dict[str, Any], value))
            except json.JSONDecodeError:
                self._stderr.append(f"non-JSON bridge output: {line.rstrip()}")

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        for line in self._process.stderr:
            self._stderr.append(line.rstrip())
            if len(self._stderr) > 50:
                del self._stderr[:-50]

    def request(self, operation: str, **payload: Any) -> Any:
        if self._closed:
            raise LiveS1Error("Connector SDK bridge is closed")
        self._sequence += 1
        request_id = self._sequence
        message = {"id": request_id, "op": operation, **payload}
        if self._process.poll() is not None or self._process.stdin is None:
            raise LiveS1Error(f"Connector SDK bridge exited: {' | '.join(self._stderr)}")
        self._process.stdin.write(canonical_json(message) + "\n")
        self._process.stdin.flush()
        deadline = time.monotonic() + self._timeout
        deferred: list[dict[str, Any]] = []
        try:
            while time.monotonic() < deadline:
                try:
                    response = self._responses.get(timeout=max(0.01, deadline - time.monotonic()))
                except queue.Empty as error:
                    raise LiveS1Error(
                        f"Connector SDK bridge timed out during {operation}"
                    ) from error
                if response.get("id") != request_id:
                    deferred.append(response)
                    continue
                if response.get("ok") is not True:
                    detail = f"Connector SDK {operation} failed: {response.get('error')}"
                    if (
                        operation == "observe_bundle"
                        and response.get("error_kind") == "transient_observation_race"
                        and response.get("error_code") == "stale_state"
                        and response.get("http_status") == 409
                        and response.get("retry_scope") == "whole_observation_bundle"
                    ):
                        raise StaleObservationError(detail)
                    raise LiveS1Error(detail)
                return response.get("result")
        finally:
            for response in deferred:
                self._responses.put(response)
        raise LiveS1Error(f"Connector SDK bridge timed out during {operation}")

    def connect(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.request("connect"))

    def observe_bundle(self, model_read_policy: Mapping[str, Any]) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.request("observe_bundle", model_read_policy=dict(model_read_policy)),
        )

    def acquire(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.request("acquire"))

    def release(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.request("release"))

    def submit(self, *, request_id: str, snapshot_id: str, bound_action_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.request(
                "submit",
                request_id=request_id,
                expected_snapshot_id=snapshot_id,
                bound_action_id=bound_action_id,
            ),
        )

    def close(self) -> None:
        if self._closed:
            return
        with suppress(LiveS1Error):
            self.request("close")
        self._closed = True
        if self._process.stdin is not None:
            self._process.stdin.close()
        try:
            self._process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._process.terminate()


def refresh_observation_bundle(
    bridge: Any,
    *,
    max_attempts: int,
    base_backoff_seconds: float,
    model_read_policy: Mapping[str, Any] | None = None,
    on_stale: Callable[[int, float, StaleObservationError], None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    """Return one coherent bundle or defer after bounded whole-bundle refreshes.

    A stale Read invalidates its Snapshot and every other Read from that attempt.
    This function performs observation only and has no action-submission port.
    """

    if max_attempts <= 0:
        raise ValueError("observation refresh max_attempts must be positive")
    if base_backoff_seconds < 0:
        raise ValueError("observation refresh backoff must be non-negative")
    for attempt in range(1, max_attempts + 1):
        try:
            if model_read_policy is None:
                return cast(dict[str, Any], bridge.observe_bundle())
            return cast(
                dict[str, Any], bridge.observe_bundle(model_read_policy=model_read_policy)
            )
        except StaleObservationError as error:
            delay = (
                base_backoff_seconds * (2 ** (attempt - 1))
                if attempt < max_attempts
                else 0.0
            )
            if on_stale is not None:
                on_stale(attempt, delay, error)
            if delay:
                sleeper(delay)
    return None


class HandoffManager:
    """Explicit Human/Qwen control state with release on every safety boundary."""

    def __init__(self, bridge: Any) -> None:
        self.bridge = bridge
        self.auto_enabled = False
        self.controller_acquired = False
        self.tainted = False
        self.taint_reason: str | None = None

    @property
    def mode(self) -> str:
        return "QWEN AUTO" if self.auto_enabled else "HUMAN"

    def acquire(self) -> Mapping[str, Any]:
        if self.tainted:
            raise LiveS1Error(f"controller is fail-closed: {self.taint_reason}")
        state = cast(Mapping[str, Any], self.bridge.acquire())
        self.controller_acquired = True
        return state

    def release(self) -> Mapping[str, Any]:
        try:
            state = cast(Mapping[str, Any], self.bridge.release())
        finally:
            self.controller_acquired = False
        return state

    def human(self) -> None:
        self.auto_enabled = False
        if self.controller_acquired:
            self.release()

    def toggle_auto(self) -> bool:
        if self.auto_enabled:
            self.human()
        elif not self.tainted:
            self.auto_enabled = True
        return self.auto_enabled

    def fail_closed(self, reason: str) -> None:
        self.auto_enabled = False
        self.tainted = True
        self.taint_reason = reason
        if self.controller_acquired:
            try:
                self.release()
            except Exception:  # TTL remains the Connector's crash-safe release path.
                self.controller_acquired = False


def apply_delivery_safety(
    handoff: HandoffManager, *, delivery: str, reason: str, one_step: bool
) -> str:
    """Apply the no-retry live delivery policy and return its disposition."""

    if delivery == "unknown":
        handoff.fail_closed(f"UNKNOWN_DELIVERY:{reason}")
        return "stop_no_retry"
    if delivery == "not_delivered":
        if "stale" in reason.lower():
            if one_step and handoff.controller_acquired:
                handoff.release()
            return "observe_fresh_no_retry"
        handoff.fail_closed(f"NOT_DELIVERED:{reason}")
        return "stop_no_retry"
    if delivery == "delivered":
        if one_step and handoff.controller_acquired:
            handoff.release()
        return "delivered"
    handoff.fail_closed(f"UNKNOWN_RECEIPT_DELIVERY:{delivery}")
    raise LiveS1Error(f"unknown receipt delivery classification: {delivery}")


@dataclass
class ResidentS1Model:
    scorer: Scheme1Scorer
    projector: ResearchProjectorV0
    serializer: Any
    identity: CheckpointIdentity
    trainer_state: TrainerState
    checkpoint_sha256: str
    qwen_load_seconds: float

    def project_and_score(
        self,
        snapshot: Mapping[str, Any],
        reads: Mapping[str, Mapping[str, Any]],
        *,
        game_version: str,
        game_commit: str,
    ) -> tuple[ProjectedDecision, list[str], list[float], float]:
        prefix = f"live-{uuid4().hex}"
        decision = self.projector.project(
            snapshot,
            reads,
            game_version=game_version,
            game_commit=game_commit,
            mutation_request_prefix=prefix,
        )
        if len(decision.actions) != len(snapshot["bound_actions"]["actions"]):
            raise LiveS1Error("projection changed the Connector candidate count")
        kinds = {action.kind for action in decision.actions}
        if not kinds.issubset(SUPPORTED_ACTION_KINDS):
            raise LiveS1Error(f"projection produced unsupported action kinds: {sorted(kinds)}")
        state_text = self.serializer.serialize_state(decision.state)
        action_texts = tuple(
            self.serializer.serialize_action(action) for action in decision.actions
        )
        started = time.perf_counter()
        scores = [float(value) for value in self.scorer.score(state_text, action_texts)]
        if self.scorer.training:
            raise LiveS1Error("live scorer unexpectedly entered training mode")
        ensure_score_alignment(scores, decision.actions)
        if not all(math.isfinite(value) for value in scores):
            raise LiveS1Error("model produced a non-finite candidate score")
        return decision, list(action_texts), scores, (time.perf_counter() - started) * 1000


def load_resident_s1(config_path: Path = DEFAULT_CONFIG) -> tuple[ResidentS1Model, dict[str, Any]]:
    """Load and verify the exact frozen Qwen plus exact trained linear head once."""

    config_path = config_path.expanduser().resolve()
    config = _json_object(config_path)
    if config.get("schema") != "stpd/s1-human-combat-live-config-v1":
        raise LiveS1Error("unsupported live config schema")
    validate_model_read_policy(config.get("model_read_policy"))
    ready_path = (ROOT / str(config["ready_path"])).resolve()
    if _sha256(ready_path) != config.get("ready_sha256"):
        raise LiveS1Error("READY_TO_TRAIN identity drift")
    ready = _json_object(ready_path)
    checkpoint = (ROOT / str(config["checkpoint_path"])).resolve()
    if _sha256(checkpoint) != config.get("checkpoint_sha256"):
        raise LiveS1Error("live checkpoint checksum drift")
    manifest = _json_object(checkpoint.with_suffix(checkpoint.suffix + ".manifest.json"))
    if manifest.get("checkpoint_sha256") != config.get("checkpoint_sha256"):
        raise LiveS1Error("checkpoint manifest differs from live config")
    identity_value = manifest.get("identity")
    if not isinstance(identity_value, Mapping):
        raise LiveS1Error("checkpoint identity is absent")
    qwen_value = identity_value.get("qwen")
    if not isinstance(qwen_value, Mapping):
        raise LiveS1Error("checkpoint Qwen identity is absent")
    expected_identity = CheckpointIdentity(
        source_revision=str(identity_value["source_revision"]),
        data_manifest_hash=str(identity_value["data_manifest_hash"]),
        architecture_id=str(identity_value["architecture_id"]),
        config_hash=str(identity_value["config_hash"]),
        serializer_version=str(identity_value["serializer_version"]),
        input_profile=str(identity_value["input_profile"]),
        qwen=_qwen_identity(cast(Mapping[str, Any], qwen_value)),
    )
    if expected_identity.identity_hash != manifest.get("identity_hash"):
        raise LiveS1Error("checkpoint identity hash drift")
    if expected_identity.source_revision != config.get("training_source_revision"):
        raise LiveS1Error("training source revision drift")
    if expected_identity.architecture_id != "scheme1-linear-pretrained":
        raise LiveS1Error("live runner requires the trained Scheme1 linear architecture")
    qwen_ready = ready.get("qwen")
    if not isinstance(qwen_ready, Mapping):
        raise LiveS1Error("READY Qwen identity is absent")
    cache_dir = Path(str(qwen_ready["cache_dir"])).resolve()
    pin = load_l2_pin()
    artifact = inspect_l2_cache(cache_dir, pin)
    if artifact.to_dict() != qwen_ready.get("artifact"):
        raise LiveS1Error("local Qwen snapshot differs from READY")
    backend = RealQwenBackend(
        l2_snapshot_path(cache_dir, pin),
        control="pretrained",
        device="cuda:0",
        micro_batch_size=int(config.get("micro_batch_size", 8)),
        feature_dtype=torch.float32,
        pin=pin,
    )
    cache = CachingQwenBackend(backend)
    if asdict(cache.identity) != asdict(expected_identity.qwen):
        raise LiveS1Error("resident Qwen identity differs from checkpoint")
    model = Scheme1Scorer(cache, backend.hidden_size, head="linear").to(backend.device)
    trainer_state = CheckpointManager().load_model_for_inference(
        checkpoint, model=model, expected_identity=expected_identity
    )
    model.eval()
    if trainer_state.optimizer_steps != config.get("optimizer_steps"):
        raise LiveS1Error("checkpoint trainer state differs from live config")
    if not backend.parameters_frozen() or not backend.parameter_gradients_absent():
        raise LiveS1Error("Qwen is not fully frozen for live inference")
    serializer = model_serializer(
        expected_identity.serializer_version,
        InputProfile(expected_identity.input_profile),
    )
    return (
        ResidentS1Model(
            model,
            ResearchProjectorV0(),
            serializer,
            expected_identity,
            trainer_state,
            str(config["checkpoint_sha256"]),
            backend.load_seconds,
        ),
        config,
    )


class LiveEvidence:
    """Append-only, local evidence for one experimental live process."""

    def __init__(self, root: Path, manifest: Mapping[str, Any]) -> None:
        root.mkdir(parents=True, exist_ok=False)
        self.root = root
        self.events = root / "events.jsonl"
        (root / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8")

    def append(self, kind: str, **payload: Any) -> None:
        record = {
            "schema": "stpd/experimental-live-s1-event-v1",
            "recorded_at": datetime.now(UTC).isoformat(),
            "kind": kind,
            **payload,
        }
        with self.events.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
