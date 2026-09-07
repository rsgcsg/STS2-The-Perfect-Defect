"""Research-owned Full-Run transitions with explicit source evidence boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..canonical import semantic_hash
from ..json_boundary import (
    BoundaryError,
    FrozenObject,
    array,
    digest,
    object_fields,
    text,
    unsigned,
)

TRANSITION_SCHEMA = "stpd/research-transition-v1"


def _object(value: object, stage: str) -> FrozenObject:
    if not isinstance(value, dict):
        raise BoundaryError(stage, "expected_object")
    return FrozenObject.of(value)


def _boolean(value: object, stage: str) -> bool:
    if type(value) is not bool:
        raise BoundaryError(stage, "expected_boolean")
    return value


@dataclass(frozen=True)
class AdmittedRead:
    kind: str
    content: FrozenObject
    evidence_ref: str
    minimum_profile: str = "standard"

    def __post_init__(self) -> None:
        text(self.kind, "read.kind")
        digest(self.evidence_ref, "read.evidence")
        if not isinstance(self.content, FrozenObject):
            raise BoundaryError("read", "mutable_content")
        if self.minimum_profile not in {"lite", "standard", "full"}:
            raise BoundaryError("read", "unknown_profile")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "content": self.content.value(),
            "evidence_ref": self.evidence_ref,
            "minimum_profile": self.minimum_profile,
        }

    @classmethod
    def decode(cls, value: object) -> AdmittedRead:
        obj = object_fields(value, {"kind", "content", "evidence_ref", "minimum_profile"}, "read")
        return cls(
            obj["kind"],
            _object(obj["content"], "read.content"),
            obj["evidence_ref"],
            obj["minimum_profile"],
        )


@dataclass(frozen=True)
class SemanticState:
    run: FrozenObject
    decision: FrozenObject
    visible_entities: tuple[FrozenObject, ...] = ()
    reads: tuple[AdmittedRead, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.run, FrozenObject) or not isinstance(self.decision, FrozenObject):
            raise BoundaryError("state", "mutable_semantic_state")
        if (
            not isinstance(self.visible_entities, tuple)
            or not isinstance(self.reads, tuple)
            or any(not isinstance(e, FrozenObject) for e in self.visible_entities)
            or any(not isinstance(r, AdmittedRead) for r in self.reads)
        ):
            raise BoundaryError("state", "untyped_semantic_content")

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundary": "semantic_execution",
            "run": self.run.value(),
            "decision": self.decision.value(),
            "visible_entities": [entity.value() for entity in self.visible_entities],
            "reads": [read.to_dict() for read in self.reads],
        }

    @classmethod
    def decode(cls, value: object) -> SemanticState:
        obj = object_fields(
            value, {"boundary", "run", "decision", "visible_entities", "reads"}, "state"
        )
        if obj["boundary"] != "semantic_execution":
            raise BoundaryError("state", "human_observation_is_not_semantic_state")
        return cls(
            _object(obj["run"], "state.run"),
            _object(obj["decision"], "state.decision"),
            tuple(_object(e, "state.entity") for e in array(obj["visible_entities"], "state")),
            tuple(AdmittedRead.decode(r) for r in array(obj["reads"], "state.reads")),
        )


@dataclass(frozen=True)
class SemanticAction:
    key: str
    kind: str
    subject: FrozenObject = FrozenObject()
    arguments: FrozenObject = FrozenObject()

    def __post_init__(self) -> None:
        text(self.key, "action.key")
        text(self.kind, "action.kind")
        if not isinstance(self.subject, FrozenObject) or not isinstance(
            self.arguments, FrozenObject
        ):
            raise BoundaryError("action", "mutable_semantic_action")

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject": self.subject.value(),
            "arguments": self.arguments.value(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, **self.semantic_dict()}

    @classmethod
    def decode(cls, value: object) -> SemanticAction:
        obj = object_fields(value, {"key", "kind", "subject", "arguments"}, "action")
        return cls(
            obj["key"],
            obj["kind"],
            _object(obj["subject"], "action.subject"),
            _object(obj["arguments"], "action.arguments"),
        )


@dataclass(frozen=True)
class EvidenceLink:
    bundle_sha256: str
    record_id: str
    environment_identity: str
    scope: str
    qualification_ref: str
    native_root_ref: str
    catalog_ref: str | None
    commit_ref: str | None
    successor_ref: str | None

    def __post_init__(self) -> None:
        digest(self.bundle_sha256, "source.bundle")
        digest(self.environment_identity, "source.environment")
        digest(self.qualification_ref, "source.qualification")
        text(self.record_id, "source.record")
        text(self.native_root_ref, "source.root")
        if self.scope not in {"engineering", "platform_qualified"}:
            raise BoundaryError("source", "unknown_evidence_scope")
        for value in (self.catalog_ref, self.commit_ref, self.successor_ref):
            if value is not None:
                digest(value, "source.witness")

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_sha256": self.bundle_sha256,
            "record_id": self.record_id,
            "environment_identity": self.environment_identity,
            "scope": self.scope,
            "qualification_ref": self.qualification_ref,
            "native_root_ref": self.native_root_ref,
            "catalog_ref": self.catalog_ref,
            "commit_ref": self.commit_ref,
            "successor_ref": self.successor_ref,
        }

    @classmethod
    def decode(cls, value: object) -> EvidenceLink:
        obj = object_fields(
            value,
            {
                "bundle_sha256",
                "record_id",
                "environment_identity",
                "scope",
                "qualification_ref",
                "native_root_ref",
                "catalog_ref",
                "commit_ref",
                "successor_ref",
            },
            "source",
        )
        return cls(**obj)


@dataclass(frozen=True)
class ResearchTransitionV1:
    run_id: str
    episode_id: str
    step_index: int
    domain: str
    family: str
    surface: str
    state: SemanticState
    actions: tuple[SemanticAction, ...]
    catalog_complete: bool
    catalog_count: int
    chosen_key: str | None
    successor: SemanticState | None
    terminal: bool
    disposition: str
    provenance: EvidenceLink

    def __post_init__(self) -> None:
        for name in ("run_id", "episode_id", "domain", "family", "surface"):
            text(getattr(self, name), "transition." + name)
        unsigned(self.step_index, "transition.step")
        unsigned(self.catalog_count, "transition.catalog_count")
        _boolean(self.catalog_complete, "transition.catalog_complete")
        _boolean(self.terminal, "transition.terminal")
        if (
            not isinstance(self.state, SemanticState)
            or not isinstance(self.provenance, EvidenceLink)
            or not isinstance(self.actions, tuple)
            or any(not isinstance(action, SemanticAction) for action in self.actions)
            or (self.successor is not None and not isinstance(self.successor, SemanticState))
        ):
            raise BoundaryError("transition", "untyped_boundary")
        keys = [action.key for action in self.actions]
        if len(keys) != len(set(keys)):
            raise BoundaryError("transition", "duplicate_candidate_key")
        if self.catalog_complete and (
            not keys or self.catalog_count != len(keys) or self.provenance.catalog_ref is None
        ):
            raise BoundaryError("transition", "unproved_complete_catalog")
        if self.disposition not in {"committed", "cancelled", "unknown", "unsupported"}:
            raise BoundaryError("transition", "unknown_disposition")
        if self.chosen_key is not None and self.chosen_key not in keys:
            raise BoundaryError("transition", "chosen_action_not_in_catalog")
        if self.disposition == "committed":
            if self.chosen_key is None or self.provenance.commit_ref is None:
                raise BoundaryError("transition", "missing_chosen_or_commit_evidence")
            if (
                self.successor is None and not self.terminal
            ) or self.provenance.successor_ref is None:
                raise BoundaryError("transition", "missing_causal_successor_evidence")

    @property
    def transition_id(self) -> str:
        return semantic_hash(
            {
                "schema": TRANSITION_SCHEMA,
                "bundle": self.provenance.bundle_sha256,
                "record": self.provenance.record_id,
            }
        )

    @property
    def rank_eligible(self) -> bool:
        return self.disposition == "committed" and self.catalog_complete

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": TRANSITION_SCHEMA,
            "transition_id": self.transition_id,
            "run_id": self.run_id,
            "episode_id": self.episode_id,
            "step_index": self.step_index,
            "domain": self.domain,
            "family": self.family,
            "surface": self.surface,
            "state": self.state.to_dict(),
            "actions": [a.to_dict() for a in self.actions],
            "catalog_source": "platform_semantic_catalog",
            "catalog_complete": self.catalog_complete,
            "catalog_count": self.catalog_count,
            "chosen_key": self.chosen_key,
            "successor": self.successor.to_dict() if self.successor is not None else None,
            "terminal": self.terminal,
            "disposition": self.disposition,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def decode(cls, value: object) -> ResearchTransitionV1:
        fields = {
            "schema",
            "transition_id",
            "run_id",
            "episode_id",
            "step_index",
            "domain",
            "family",
            "surface",
            "state",
            "actions",
            "catalog_source",
            "catalog_complete",
            "catalog_count",
            "chosen_key",
            "successor",
            "terminal",
            "disposition",
            "provenance",
        }
        obj = object_fields(value, fields, "transition")
        if obj["schema"] != TRANSITION_SCHEMA:
            raise BoundaryError("transition", "unsupported_schema")
        if obj["catalog_source"] != "platform_semantic_catalog":
            raise BoundaryError("transition", "public_actions_are_not_semantic_actions")
        result = cls(
            obj["run_id"],
            obj["episode_id"],
            obj["step_index"],
            obj["domain"],
            obj["family"],
            obj["surface"],
            SemanticState.decode(obj["state"]),
            tuple(SemanticAction.decode(a) for a in array(obj["actions"], "actions")),
            obj["catalog_complete"],
            obj["catalog_count"],
            obj["chosen_key"],
            SemanticState.decode(obj["successor"]) if obj["successor"] is not None else None,
            obj["terminal"],
            obj["disposition"],
            EvidenceLink.decode(obj["provenance"]),
        )
        if result.transition_id != obj["transition_id"]:
            raise BoundaryError("transition", "identity_mismatch")
        return result


@dataclass(frozen=True)
class SourceProjection:
    """Output of a trusted source adapter, not an externally trusted qualification flag."""

    adapter_id: str
    source_sha256: str
    scope: str
    run_proofs: FrozenObject
    transitions: tuple[ResearchTransitionV1, ...]

    def __post_init__(self) -> None:
        text(self.adapter_id, "projection.adapter")
        digest(self.source_sha256, "projection.source")
        if self.scope not in {"engineering", "platform_qualified"}:
            raise BoundaryError("projection", "unknown_scope")
        if not isinstance(self.run_proofs, FrozenObject) or not isinstance(self.transitions, tuple):
            raise BoundaryError("projection", "mutable_content")
        for run_id, value in self.run_proofs.value().items():
            text(run_id, "projection.run_id")
            proof = object_fields(
                value, {"started_ref", "terminal_ref", "record_count"}, "projection.run_proof"
            )
            digest(proof["started_ref"], "projection.run_start")
            digest(proof["terminal_ref"], "projection.run_terminal")
            unsigned(proof["record_count"], "projection.record_count")
        for transition in self.transitions:
            if not isinstance(transition, ResearchTransitionV1):
                raise BoundaryError("projection", "untyped_transition")
            if (
                transition.provenance.bundle_sha256 != self.source_sha256
                or transition.provenance.scope != self.scope
            ):
                raise BoundaryError("projection", "source_identity_mismatch")


class SourceAdapter(Protocol):
    """A final Platform implementation must verify owner evidence before emitting qualified data."""

    adapter_id: str

    def project(self, raw: bytes) -> SourceProjection: ...
