"""Versioned manifest identities independent of filesystems, databases and vendors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .canonical import semantic_hash
from .json_boundary import (
    BoundaryError,
    FrozenObject,
    array,
    decode_json,
    digest,
    json_bytes,
    object_fields,
    text,
    unsigned,
)

MANIFEST_SCHEMA = "stpd/artifact-manifest-v1"
KINDS = frozenset(
    {
        "evidence",
        "dataset",
        "model_view",
        "feature_set",
        "training_input",
        "experiment",
        "run",
        "checkpoint",
        "model",
        "offline_evaluation",
        "live_evaluation",
        "performance",
        "run_event",
        "run_result",
        "gold_tasks",
        "gold_labels",
        "protocol",
        "analysis",
    }
)


@dataclass(frozen=True)
class Producer:
    repository: str
    source_revision: str
    uv_lock_sha256: str

    def __post_init__(self) -> None:
        text(self.repository, "producer.repository")
        digest(self.source_revision, "producer.source_revision", length=40)
        digest(self.uv_lock_sha256, "producer.uv_lock_sha256")

    def to_dict(self) -> dict[str, str]:
        return {
            "repository": self.repository,
            "source_revision": self.source_revision,
            "uv_lock_sha256": self.uv_lock_sha256,
        }

    @classmethod
    def decode(cls, value: object) -> Producer:
        obj = object_fields(value, {"repository", "source_revision", "uv_lock_sha256"}, "producer")
        return cls(obj["repository"], obj["source_revision"], obj["uv_lock_sha256"])


@dataclass(frozen=True, order=True)
class Parent:
    role: str
    artifact_id: str

    def __post_init__(self) -> None:
        text(self.role, "parent.role", maximum=128)
        digest(self.artifact_id, "parent.artifact_id")

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "artifact_id": self.artifact_id}


@dataclass(frozen=True, order=True)
class Payload:
    role: str
    sha256: str
    size: int
    media_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        text(self.role, "payload.role", maximum=128)
        digest(self.sha256, "payload.sha256")
        unsigned(self.size, "payload.size")
        text(self.media_type, "payload.media_type", maximum=128)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "sha256": self.sha256,
            "size": self.size,
            "media_type": self.media_type,
        }

    @classmethod
    def decode(cls, value: object) -> Payload:
        obj = object_fields(value, {"role", "sha256", "size", "media_type"}, "payload")
        return cls(obj["role"], obj["sha256"], obj["size"], obj["media_type"])


@dataclass(frozen=True)
class Manifest:
    kind: str
    producer: Producer
    parents: tuple[Parent, ...] = ()
    payloads: tuple[Payload, ...] = ()
    parameters: FrozenObject = FrozenObject()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in KINDS:
            raise BoundaryError("manifest", "unknown_kind")
        if (
            not isinstance(self.parents, tuple)
            or not isinstance(self.payloads, tuple)
            or any(not isinstance(p, Parent) for p in self.parents)
            or any(not isinstance(p, Payload) for p in self.payloads)
        ):
            raise BoundaryError("manifest", "mutable_or_untyped_collections")
        if len(set(self.parents)) != len(self.parents):
            raise BoundaryError("manifest", "duplicate_parent")
        if len({p.role for p in self.payloads}) != len(self.payloads):
            raise BoundaryError("manifest", "duplicate_payload_role")
        if not isinstance(self.producer, Producer) or not isinstance(self.parameters, FrozenObject):
            raise BoundaryError("manifest", "untyped_boundary")

    def body(self) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "kind": self.kind,
            "producer": self.producer.to_dict(),
            "parents": [p.to_dict() for p in sorted(self.parents)],
            "payloads": [p.to_dict() for p in sorted(self.payloads)],
            "parameters": self.parameters.value(),
        }

    @property
    def artifact_id(self) -> str:
        return semantic_hash(self.body())

    def to_bytes(self) -> bytes:
        return json_bytes({**self.body(), "artifact_id": self.artifact_id})

    def parent(self, role: str) -> str:
        matches = [p.artifact_id for p in self.parents if p.role == role]
        if len(matches) != 1:
            raise BoundaryError("manifest.parent", "missing_or_ambiguous_role")
        return matches[0]

    def payload(self, role: str) -> Payload:
        matches = [p for p in self.payloads if p.role == role]
        if len(matches) != 1:
            raise BoundaryError("manifest.payload", "missing_or_ambiguous_role")
        return matches[0]

    @classmethod
    def from_bytes(cls, raw: bytes, expected_id: str | None = None) -> Manifest:
        obj = object_fields(
            decode_json(raw),
            {
                "schema",
                "artifact_id",
                "kind",
                "producer",
                "parents",
                "payloads",
                "parameters",
            },
            "manifest",
        )
        if obj["schema"] != MANIFEST_SCHEMA:
            raise BoundaryError("manifest", "unsupported_schema")
        parents = []
        for item in array(obj["parents"], "manifest.parents"):
            parent = object_fields(item, {"role", "artifact_id"}, "manifest.parent")
            parents.append(Parent(parent["role"], parent["artifact_id"]))
        if not isinstance(obj["parameters"], dict):
            raise BoundaryError("manifest.parameters", "not_an_object")
        result = cls(
            obj["kind"],
            Producer.decode(obj["producer"]),
            tuple(parents),
            tuple(Payload.decode(p) for p in array(obj["payloads"], "manifest.payloads")),
            FrozenObject.of(obj["parameters"]),
        )
        if obj["artifact_id"] != result.artifact_id or (
            expected_id is not None
            and digest(expected_id, "manifest.expected") != result.artifact_id
        ):
            raise BoundaryError("manifest", "identity_mismatch")
        if raw != result.to_bytes():
            raise BoundaryError("manifest", "non_canonical_bytes")
        return result
