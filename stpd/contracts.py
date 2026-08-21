"""Stable insertion points for STPD's external and cross-layer contracts.

The current smoke lane does not depend on these protocols yet.  They define the
minimum boundaries that future data, Qwen, model, training, and evaluation code
must preserve without importing Headless or Connector implementation details.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Sequence, runtime_checkable


class ContractError(ValueError):
    """Raised when a versioned STPD identity or interface value is incomplete."""


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")


@dataclass(frozen=True)
class EnvironmentIdentity:
    """Exact game, Host, Connector, and information-policy identity."""

    game_version: str
    game_commit: str
    host_source_revision: str
    host_artifact_sha256: str
    connector_version: str
    connector_artifact_sha256: str
    information_policy_id: str

    def validate(self) -> None:
        for name, value in (
            ("game_version", self.game_version),
            ("game_commit", self.game_commit),
            ("host_source_revision", self.host_source_revision),
            ("host_artifact_sha256", self.host_artifact_sha256),
            ("connector_version", self.connector_version),
            ("connector_artifact_sha256", self.connector_artifact_sha256),
            ("information_policy_id", self.information_policy_id),
        ):
            _require_text(name, value)


@dataclass(frozen=True)
class TransitionEligibility:
    """Independent permissions for ranking, dynamics, and return supervision."""

    rank: bool
    transition: bool
    return_: bool

    def validate(self) -> None:
        if not (self.rank or self.transition or self.return_):
            raise ContractError("a transition must be eligible for at least one use")


@dataclass(frozen=True)
class QwenIdentity:
    """Pinned encoder identity required by a reproducible v0 run."""

    model_id: str
    model_revision: str
    tokenizer_revision: str
    dtype: str
    device: str
    frozen: bool

    def validate(self) -> None:
        for name, value in (
            ("model_id", self.model_id),
            ("model_revision", self.model_revision),
            ("tokenizer_revision", self.tokenizer_revision),
            ("dtype", self.dtype),
            ("device", self.device),
        ):
            _require_text(name, value)

    def validate_v0(self) -> None:
        self.validate()
        if not self.frozen:
            raise ContractError("the v0 core Qwen backbone must be frozen")


@runtime_checkable
class PlayerEnvironmentPort(Protocol):
    """Strategy-free public Player Environment consumed by STPD."""

    ready: Mapping[str, Any]

    def reset(self, seed: str) -> Mapping[str, Any]:
        ...

    def observe(self) -> Mapping[str, Any]:
        ...

    def read(self, read_id: str, snapshot_id: str) -> Mapping[str, Any]:
        ...

    def step(
        self,
        bound_action_id: str,
        snapshot_id: str,
        mutation_request_id: Optional[str] = None,
    ) -> Mapping[str, Any]:
        ...

    def close(self) -> None:
        ...


@runtime_checkable
class ResearchProjector(Protocol):
    """Converts coherent public environment facts into research objects."""

    def project_state(
        self,
        snapshot: Mapping[str, Any],
        reads: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        ...

    def project_actions(self, snapshot: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        ...


@runtime_checkable
class ModelSerializer(Protocol):
    """Deterministic, versioned ResearchState/Action serialization."""

    profile_id: str

    def serialize_state(self, research_state: Mapping[str, Any]) -> str:
        ...

    def serialize_action(self, research_action: Mapping[str, Any]) -> str:
        ...


@runtime_checkable
class QwenBackend(Protocol):
    """Frozen encoder operations used by the v0 model families."""

    identity: QwenIdentity

    def encode_joint(
        self,
        state_texts: Sequence[str],
        action_texts: Sequence[str],
    ) -> Any:
        ...

    def encode_state(self, state_texts: Sequence[str], *, return_sequence: bool) -> Any:
        ...

    def embed_action_tokens(self, action_texts: Sequence[str]) -> Any:
        ...


@runtime_checkable
class ActionScorer(Protocol):
    """Returns one scalar score for each current legal candidate."""

    def score(self, model_state: str, model_actions: Sequence[str]) -> Sequence[float]:
        ...


def ensure_score_alignment(scores: Sequence[float], actions: Sequence[Any]) -> None:
    """Fail when a scorer invents, drops, or reorders the candidate count."""

    if len(scores) != len(actions):
        raise ContractError(
            f"score/action count mismatch: {len(scores)} scores for {len(actions)} actions"
        )
    if not actions:
        raise ContractError("cannot score an empty legal action set")
