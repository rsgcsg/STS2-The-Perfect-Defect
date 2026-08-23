"""Collect one exact stable Player Environment decision into ResearchTransition v0."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..contracts import EnvironmentIdentity, PlayerEnvironmentPort, TransitionEligibility
from ..representation import InputProfile, PolicyProvenance, ResearchState, ResearchTransition
from .projector import ProjectedDecision, ResearchProjectorV0


class CollectionError(RuntimeError):
    """Classified fail-closed collection error; never an invitation to retry unknown."""


ActionPolicy = Callable[[ProjectedDecision], str]


@dataclass(frozen=True)
class CollectedTransition:
    transition: ResearchTransition
    snapshot: Mapping[str, Any]
    reads: Mapping[str, Mapping[str, Any]]
    receipt: Mapping[str, Any]
    successor: Mapping[str, Any]
    successor_reads: Mapping[str, Mapping[str, Any]]


class StableTransitionCollector:
    def __init__(
        self,
        environment: PlayerEnvironmentPort,
        projector: ResearchProjectorV0,
        *,
        environment_identity: EnvironmentIdentity,
        policy: PolicyProvenance,
        input_profile: InputProfile,
        read_kinds: Sequence[str] = (),
        settling_timeout_seconds: float = 20.0,
        polling_interval_seconds: float = 0.02,
    ) -> None:
        self.environment = environment
        self.projector = projector
        self.environment_identity = environment_identity
        self.policy = policy
        self.input_profile = input_profile
        self.read_kinds = tuple(read_kinds)
        if settling_timeout_seconds <= 0 or polling_interval_seconds < 0:
            raise ValueError("settling timeout must be positive and polling interval non-negative")
        self.settling_timeout_seconds = settling_timeout_seconds
        self.polling_interval_seconds = polling_interval_seconds
        environment_identity.validate()
        policy.validate()

    def _reads(self, snapshot: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        available: dict[str, list[Mapping[str, Any]]] = {}
        required = set(self.read_kinds)
        for descriptor in snapshot.get("reads", []):
            if not isinstance(descriptor, Mapping):
                continue
            kind = str(descriptor.get("kind"))
            if kind in required:
                available.setdefault(kind, []).append(descriptor)
        result: dict[str, Mapping[str, Any]] = {}
        for kind in self.read_kinds:
            descriptors = available.get(kind, [])
            if not descriptors:
                raise CollectionError(f"required fair-player Read is unavailable: {kind}")
            if len(descriptors) != 1:
                raise CollectionError(
                    f"required fair-player Read kind is not unique: {kind}"
                )
            descriptor = descriptors[0]
            read_id = descriptor.get("read_id")
            if not isinstance(read_id, str) or not read_id:
                raise CollectionError(f"Read identity is missing: {kind}")
            value = self.environment.read(read_id, str(snapshot["snapshot_id"]))
            if not isinstance(value, Mapping):
                raise CollectionError(f"Read did not return an object: {kind}")
            completeness = value.get("completeness")
            if isinstance(completeness, Mapping) and completeness.get("status") != "complete":
                raise CollectionError(f"required fair-player Read is incomplete: {kind}")
            result[kind] = value
        return result

    @staticmethod
    def _runtime_instance(snapshot: Mapping[str, Any]) -> str:
        session = snapshot.get("session")
        runtime = session.get("runtime_instance_id") if isinstance(session, Mapping) else None
        if not isinstance(runtime, str) or not runtime:
            raise CollectionError("snapshot runtime identity is missing")
        return runtime

    def _stable_successor(self, candidate: Mapping[str, Any]) -> Mapping[str, Any]:
        snapshot = candidate
        deadline = time.monotonic() + self.settling_timeout_seconds
        while True:
            status = snapshot.get("status")
            if status in {"interactive", "visible_unsupported", "observed"}:
                return snapshot
            if status != "settling":
                raise CollectionError(f"unknown successor readiness state: {status}")
            if time.monotonic() >= deadline:
                raise CollectionError("settling timeout while waiting for stable successor")
            if self.polling_interval_seconds:
                time.sleep(self.polling_interval_seconds)
            snapshot = self.environment.observe()

    def collect_one(
        self,
        snapshot: Mapping[str, Any],
        *,
        choose: ActionPolicy,
        transition_id: str,
        episode_id: str,
        step_index: int,
        seed: str,
        raw_ref: str,
        rank_eligible: bool,
    ) -> CollectedTransition:
        reads = self._reads(snapshot)
        projected = self.projector.project(
            snapshot,
            reads,
            game_version=self.environment_identity.game_version,
            game_commit=self.environment_identity.game_commit,
            mutation_request_prefix=transition_id,
        )
        action_key = choose(projected)
        envelope = next(
            (item for item in projected.envelopes if item.action_key == action_key), None
        )
        if envelope is None:
            raise CollectionError("policy selected an action outside the current semantic catalog")
        receipt = self.environment.step(
            envelope.bound_action_id,
            envelope.snapshot_id,
            envelope.mutation_request_id,
        )
        delivery = receipt.get("delivery")
        if delivery == "unknown":
            raise CollectionError("unknown delivery invalidates the episode and must not retry")
        if delivery != "delivered":
            raise CollectionError(
                f"action was not delivered: {delivery}:{receipt.get('reason_code')}"
            )
        if receipt.get("request_id") != envelope.mutation_request_id:
            raise CollectionError("receipt request identity mismatch")
        receipt_action = receipt.get("action")
        if (
            not isinstance(receipt_action, Mapping)
            or receipt_action.get("bound_action_id") != envelope.bound_action_id
        ):
            raise CollectionError("receipt action identity mismatch")
        successor_raw = receipt.get("successor")
        if not isinstance(successor_raw, Mapping):
            raise CollectionError("delivered action has no successor observation")
        if successor_raw.get("snapshot_id") == snapshot.get("snapshot_id"):
            raise CollectionError("delivered action did not advance snapshot identity")
        successor_raw = self._stable_successor(successor_raw)
        observed = self._stable_successor(self.environment.observe())
        if self._runtime_instance(observed) != self._runtime_instance(snapshot):
            raise CollectionError("runtime identity changed during successor verification")
        if int(observed.get("sequence", -1)) < int(successor_raw.get("sequence", -1)):
            raise CollectionError("independent successor observation moved backwards")
        successor_raw = observed
        if self._runtime_instance(successor_raw) != self._runtime_instance(snapshot):
            raise CollectionError("runtime identity changed across one transition")
        successor_kind = str(
            successor_raw.get("interaction", {}).get("kind", "")
            if isinstance(successor_raw.get("interaction"), Mapping)
            else ""
        )
        terminal = successor_kind == "game_over"
        scope_exit = not terminal and not (
            successor_kind == "combat_turn"
            or "selection" in successor_kind
            or "choice" in successor_kind
        )
        successor_state: ResearchState | None = None
        successor_reads: dict[str, Mapping[str, Any]] = {}
        if not terminal and not scope_exit:
            successor_reads = self._reads(successor_raw)
            successor_state = self.projector.project(
                successor_raw,
                successor_reads,
                game_version=self.environment_identity.game_version,
                game_commit=self.environment_identity.game_commit,
                mutation_request_prefix=f"{transition_id}-successor",
            ).state
        chosen = next(action for action in projected.actions if action.action_key == action_key)
        eligibility = TransitionEligibility(
            rank_eligible,
            "full_listwise" if rank_eligible else "none",
            True,
            False,
            "complete",
        )
        transition = ResearchTransition(
            transition_id,
            episode_id,
            step_index,
            seed,
            self.environment_identity,
            self.policy,
            "combat",
            projected.state.surface,
            self.input_profile,
            eligibility,
            projected.state,
            projected.actions,
            chosen,
            successor_state,
            terminal,
            scope_exit,
            None,
            raw_ref,
        )
        transition.validate()
        return CollectedTransition(
            transition,
            snapshot,
            reads,
            receipt,
            successor_raw,
            successor_reads,
        )
