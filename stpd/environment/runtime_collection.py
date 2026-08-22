"""Bounded current-runtime collection through the public Player Environment port."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ..canonical import canonical_json, semantic_hash, to_json_value
from ..contracts import ContractError, EnvironmentIdentity, PlayerEnvironmentPort
from ..representation import InputProfile, ModelSerializerV0, PolicyProvenance, ResearchTransition
from ..training_smoke import action_list, choose_noncombat_action
from .collector import CollectedTransition, StableTransitionCollector
from .identity import environment_identity_from_managed_ready
from .projector import ProjectedDecision, ResearchProjectorV0


@dataclass(frozen=True)
class RuntimeCollection:
    environment: EnvironmentIdentity
    transitions: tuple[ResearchTransition, ...]
    raw_records: tuple[Mapping[str, Any], ...]
    token_profile_records: tuple[Mapping[str, str], ...]
    environment_actions: int
    termination_reason: str

    @property
    def family_counts(self) -> dict[str, int]:
        return dict(
            sorted(Counter(item.state.decision_family.value for item in self.transitions).items())
        )


def _interaction(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    value = snapshot.get("interaction")
    if not isinstance(value, Mapping):
        raise ContractError("snapshot has no interaction object")
    return value


def _is_combat_decision(snapshot: Mapping[str, Any]) -> bool:
    interaction = _interaction(snapshot)
    content = interaction.get("content")
    context = content.get("context") if isinstance(content, Mapping) else None
    if not isinstance(context, Mapping) or context.get("kind") != "combat":
        return False
    kind = str(interaction.get("kind", ""))
    return kind == "combat_turn" or "selection" in kind or "choice" in kind


def _choose_semantic_first(projected: ProjectedDecision) -> str:
    return min(
        projected.actions,
        key=lambda action: canonical_json(
            {key: value for key, value in action.to_dict().items() if key != "action_key"}
        ),
    ).action_key


def _same_session(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return left.get("session") == right.get("session")


def _stable_observation(
    environment: PlayerEnvironmentPort,
    snapshot: Mapping[str, Any],
    *,
    timeout_seconds: float = 20.0,
    polling_interval_seconds: float = 0.02,
) -> Mapping[str, Any]:
    if timeout_seconds <= 0 or polling_interval_seconds < 0:
        raise ValueError("settling timeout must be positive and polling interval non-negative")
    current = snapshot
    deadline = time.monotonic() + timeout_seconds
    while True:
        if current.get("status") != "settling":
            return current
        if time.monotonic() >= deadline:
            raise ContractError("runtime collection exceeded its bounded settling supervision")
        if polling_interval_seconds:
            time.sleep(polling_interval_seconds)
        current = environment.observe()


def _advance_noncombat(
    environment: PlayerEnvironmentPort, snapshot: Mapping[str, Any], action_index: int
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    actions = action_list(snapshot)
    if not actions:
        raise ContractError("stable non-terminal snapshot has no BoundAction")
    selected = choose_noncombat_action(snapshot, actions)
    request_id = f"stpd-navigation-{action_index:06d}-{semantic_hash(selected)[:16]}"
    receipt = environment.step(
        str(selected["bound_action_id"]), str(snapshot["snapshot_id"]), request_id
    )
    if receipt.get("delivery") == "unknown":
        raise ContractError("unknown noncombat delivery invalidates collection and must not retry")
    if receipt.get("delivery") != "delivered":
        raise ContractError(
            "noncombat delivery failed: "
            f"{receipt.get('delivery')}:{receipt.get('reason_code')}"
        )
    if receipt.get("request_id") != request_id:
        raise ContractError("noncombat receipt request identity mismatch")
    receipt_action = receipt.get("action")
    if (
        not isinstance(receipt_action, Mapping)
        or receipt_action.get("bound_action_id") != selected.get("bound_action_id")
    ):
        raise ContractError("noncombat receipt action identity mismatch")
    successor = receipt.get("successor")
    if not isinstance(successor, Mapping):
        raise ContractError("delivered noncombat action has no successor")
    successor = _stable_observation(environment, successor)
    observed = _stable_observation(environment, environment.observe())
    if not _same_session(snapshot, successor) or not _same_session(snapshot, observed):
        raise ContractError("runtime identity changed across noncombat navigation")
    if int(observed.get("sequence", -1)) < int(successor.get("sequence", -1)):
        raise ContractError("independent noncombat observation moved backwards")
    return observed, receipt


def _required_reads(snapshot: Mapping[str, Any]) -> tuple[str, ...]:
    available = {
        descriptor.get("kind")
        for descriptor in snapshot.get("reads", ())
        if isinstance(descriptor, Mapping)
    }
    required = ("run_deck", "combat_piles")
    missing = [kind for kind in required if kind not in available]
    if missing:
        raise ContractError(f"combat snapshot is missing required fair-player Reads: {missing}")
    return required


def _raw_record(result: CollectedTransition) -> Mapping[str, Any]:
    return {
        "schema": "stpd/runtime-collection-record-v0",
        "transition_id": result.transition.transition_id,
        "snapshot": to_json_value(result.snapshot),
        "reads": to_json_value(result.reads),
        "receipt": to_json_value(result.receipt),
        "successor": to_json_value(result.successor),
        "successor_reads": to_json_value(result.successor_reads),
    }


def token_profile_records(
    transitions: tuple[ResearchTransition, ...],
) -> tuple[Mapping[str, str], ...]:
    records: list[Mapping[str, str]] = []
    for transition in transitions:
        for profile in InputProfile:
            serializer = ModelSerializerV0(profile)
            state_text = serializer.serialize_state(transition.state)
            for action in transition.legal_actions:
                records.append(
                    {
                        "profile": profile.value,
                        "family": transition.state.decision_family.value,
                        "text": f"{state_text}\n{serializer.serialize_action(action)}",
                    }
                )
    return tuple(records)


def collect_managed_runtime(
    environment: PlayerEnvironmentPort,
    *,
    seed: str,
    episode_id: str,
    max_environment_actions: int,
    max_transitions: int,
    ranking_supervision: Literal["none", "canonical-semantic-first"] = "none",
) -> RuntimeCollection:
    if max_environment_actions <= 0 or max_transitions <= 0:
        raise ValueError("collection bounds must be positive")
    if ranking_supervision not in ("none", "canonical-semantic-first"):
        raise ValueError("unsupported runtime ranking supervision mode")
    snapshot = _stable_observation(environment, environment.reset(seed))
    identity = environment_identity_from_managed_ready(environment.ready, snapshot)
    rank_eligible = ranking_supervision == "canonical-semantic-first"
    policy = PolicyProvenance(
        source=(
            "deterministic_behavior_fixture"
            if rank_eligible
            else "deterministic_environment_probe"
        ),
        version="stpd-runtime-collector-v1",
        config_hash=semantic_hash(
            {
                "selection": "canonical_semantic_first",
                "ranking_supervision": ranking_supervision,
                "rank_eligible": rank_eligible,
                "max_environment_actions": max_environment_actions,
                "max_transitions": max_transitions,
            }
        ),
        teacher_confidence=None,
    )
    projector = ResearchProjectorV0()
    transitions: list[ResearchTransition] = []
    raw_records: list[Mapping[str, Any]] = []
    termination_reason = "environment_action_limit"
    environment_actions = 0
    while environment_actions < max_environment_actions:
        kind = str(_interaction(snapshot).get("kind", ""))
        if kind == "game_over":
            termination_reason = "game_over"
            break
        if _is_combat_decision(snapshot):
            transition_id = f"{episode_id}-t{environment_actions:06d}"
            collector = StableTransitionCollector(
                environment,
                projector,
                environment_identity=identity,
                policy=policy,
                input_profile=InputProfile.STANDARD,
                read_kinds=_required_reads(snapshot),
            )
            result = collector.collect_one(
                snapshot,
                choose=_choose_semantic_first,
                transition_id=transition_id,
                episode_id=episode_id,
                step_index=environment_actions,
                seed=seed,
                raw_ref=f"raw/runtime.jsonl#{len(transitions)}",
                rank_eligible=rank_eligible,
            )
            transitions.append(result.transition)
            raw_records.append(_raw_record(result))
            snapshot = result.successor
            environment_actions += 1
            if len(transitions) >= max_transitions:
                termination_reason = "transition_limit"
                break
            continue
        snapshot, _ = _advance_noncombat(environment, snapshot, environment_actions)
        environment_actions += 1
    if not transitions:
        raise ContractError("bounded runtime collection did not reach a v0 Combat decision")
    materialized = tuple(transitions)
    return RuntimeCollection(
        identity,
        materialized,
        tuple(raw_records),
        token_profile_records(materialized),
        environment_actions,
        termination_reason,
    )
