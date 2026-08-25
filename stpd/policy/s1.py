"""S1 policy implementation without Connector or controller lifecycle ownership."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import torch

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


class S1PolicyError(RuntimeError):
    """A classified S1 policy loading, projection, or support failure."""


def validate_model_read_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or dict(value) != HUMAN_CHECKPOINT_MODEL_READ_POLICY:
        raise S1PolicyError(
            "live model Read policy differs from Human checkpoint training semantics"
        )
    return dict(HUMAN_CHECKPOINT_MODEL_READ_POLICY)


def canonicalize_prefetched_reads(reads: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(reads, Sequence) or isinstance(reads, (str, bytes, bytearray)):
        raise S1PolicyError("Connector SDK decision-bundle Reads must be an array")
    identities: set[str] = set()
    result: list[dict[str, Any]] = []
    for read_raw in reads:
        if not isinstance(read_raw, Mapping):
            raise S1PolicyError("Connector SDK decision-bundle Read must be an object")
        read = dict(read_raw)
        read_id = read.get("read_id")
        if not isinstance(read_id, str) or not read_id:
            raise S1PolicyError("Connector SDK decision-bundle Read identity is missing")
        if read_id in identities:
            raise S1PolicyError(f"duplicate Connector Read identity is unsupported: {read_id}")
        identities.add(read_id)
        result.append(read)
    return tuple(sorted(result, key=lambda read: str(read["read_id"])))


def checkpoint_model_reads(
    prefetched_reads: Sequence[Mapping[str, Any]],
    model_read_policy: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    validate_model_read_policy(model_read_policy)
    if prefetched_reads:
        raise S1PolicyError("none Read policy received unexpected prefetched Read responses")
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
        raise S1PolicyError(f"JSON root must be an object: {path}")
    return cast(dict[str, Any], value)


def _qwen_identity(value: Mapping[str, Any]) -> QwenIdentity:
    fields = QwenIdentity.__dataclass_fields__
    if set(value) != set(fields):
        raise S1PolicyError("checkpoint Qwen identity fields drifted")
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
    """Admit one complete Defect A0 ordinary-combat decision or abstain wholly."""

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
            False,
            f"SNAPSHOT_{snapshot.get('status', 'UNKNOWN')}",
            kind,
            surface,
            count,
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
    if not verbs or not verbs.issubset(SUPPORTED_VERBS):
        return SnapshotAdmission(
            False,
            f"UNSUPPORTED_ACTION_CATALOG:{','.join(sorted(verbs - SUPPORTED_VERBS))}",
            kind,
            surface,
            count,
        )
    if not capability_verbs.issubset(SUPPORTED_VERBS):
        return SnapshotAdmission(
            False,
            "UNSUPPORTED_ACTION_CAPABILITY:"
            f"{','.join(sorted(capability_verbs - SUPPORTED_VERBS))}",
            kind,
            surface,
            count,
        )
    return SnapshotAdmission(True, "SUPPORTED_COMBAT", kind, surface, count)


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
        decision = self.projector.project(
            snapshot,
            reads,
            game_version=game_version,
            game_commit=game_commit,
            mutation_request_prefix=f"live-{uuid4().hex}",
        )
        if len(decision.actions) != len(snapshot["bound_actions"]["actions"]):
            raise S1PolicyError("projection changed the Connector candidate count")
        kinds = {action.kind for action in decision.actions}
        if not kinds.issubset(SUPPORTED_ACTION_KINDS):
            raise S1PolicyError(f"projection produced unsupported action kinds: {sorted(kinds)}")
        state_text = self.serializer.serialize_state(decision.state)
        action_texts = tuple(
            self.serializer.serialize_action(action) for action in decision.actions
        )
        started = time.perf_counter()
        scores = [float(value) for value in self.scorer.score(state_text, action_texts)]
        if self.scorer.training:
            raise S1PolicyError("live scorer unexpectedly entered training mode")
        ensure_score_alignment(scores, decision.actions)
        if not all(math.isfinite(value) for value in scores):
            raise S1PolicyError("model produced a non-finite candidate score")
        return decision, list(action_texts), scores, (time.perf_counter() - started) * 1000


def load_resident_s1(config_path: Path = DEFAULT_CONFIG) -> tuple[ResidentS1Model, dict[str, Any]]:
    """Load and verify the exact frozen Qwen and trained linear head once."""

    config_path = config_path.expanduser().resolve()
    config = _json_object(config_path)
    if config.get("schema") != "stpd/s1-human-combat-live-config-v1":
        raise S1PolicyError("unsupported live config schema")
    validate_model_read_policy(config.get("model_read_policy"))
    ready_path = (ROOT / str(config["ready_path"])).resolve()
    if _sha256(ready_path) != config.get("ready_sha256"):
        raise S1PolicyError("READY_TO_TRAIN identity drift")
    ready = _json_object(ready_path)
    checkpoint = (ROOT / str(config["checkpoint_path"])).resolve()
    if _sha256(checkpoint) != config.get("checkpoint_sha256"):
        raise S1PolicyError("live checkpoint checksum drift")
    manifest = _json_object(checkpoint.with_suffix(checkpoint.suffix + ".manifest.json"))
    if manifest.get("checkpoint_sha256") != config.get("checkpoint_sha256"):
        raise S1PolicyError("checkpoint manifest differs from live config")
    identity_value = manifest.get("identity")
    if not isinstance(identity_value, Mapping):
        raise S1PolicyError("checkpoint identity is absent")
    qwen_value = identity_value.get("qwen")
    if not isinstance(qwen_value, Mapping):
        raise S1PolicyError("checkpoint Qwen identity is absent")
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
        raise S1PolicyError("checkpoint identity hash drift")
    if expected_identity.source_revision != config.get("training_source_revision"):
        raise S1PolicyError("training source revision drift")
    if expected_identity.architecture_id != "scheme1-linear-pretrained":
        raise S1PolicyError("S1 policy requires the trained Scheme1 linear architecture")
    qwen_ready = ready.get("qwen")
    if not isinstance(qwen_ready, Mapping):
        raise S1PolicyError("READY Qwen identity is absent")
    cache_dir = Path(str(qwen_ready["cache_dir"])).resolve()
    pin = load_l2_pin()
    artifact = inspect_l2_cache(cache_dir, pin)
    if artifact.to_dict() != qwen_ready.get("artifact"):
        raise S1PolicyError("local Qwen snapshot differs from READY")
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
        raise S1PolicyError("resident Qwen identity differs from checkpoint")
    model = Scheme1Scorer(cache, backend.hidden_size, head="linear").to(backend.device)
    trainer_state = CheckpointManager().load_model_for_inference(
        checkpoint,
        model=model,
        expected_identity=expected_identity,
    )
    model.eval()
    if trainer_state.optimizer_steps != config.get("optimizer_steps"):
        raise S1PolicyError("checkpoint trainer state differs from live config")
    if not backend.parameters_frozen() or not backend.parameter_gradients_absent():
        raise S1PolicyError("Qwen is not fully frozen for live inference")
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


__all__ = [
    "DEFAULT_CONFIG",
    "HUMAN_CHECKPOINT_MODEL_READ_POLICY",
    "ResidentS1Model",
    "S1PolicyError",
    "SnapshotAdmission",
    "admit_snapshot",
    "canonicalize_prefetched_reads",
    "checkpoint_model_reads",
    "load_resident_s1",
    "validate_model_read_policy",
]
