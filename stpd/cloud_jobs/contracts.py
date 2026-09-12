"""CPU-preparable feature jobs and strict, identity-bound worker requests/receipts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..artifact_contracts import Manifest, Parent, Producer
from ..canonical import semantic_hash
from ..fullrun.features import load_model_view, validate_qwen_identity
from ..json_boundary import BoundaryError, FrozenObject, digest, object_fields, text, unsigned
from ..storage.store import ArtifactStore
from ..workers.contracts import TrainingConfig

FEATURE_JOB_SCHEMA = "stpd/feature-job-v1"
REQUEST_SCHEMA = "stpd/compute-request-v1"
RECEIPT_SCHEMA = "stpd/compute-receipt-v1"


@dataclass(frozen=True)
class FeatureJobSpec:
    """Expected backend identity is supplied from the qualified target environment.

    Preparing a job does not import a model or require CUDA. In particular, the target
    torch build/version is not inferred from the Hub's CPU environment.
    """

    qwen: FrozenObject
    training: TrainingConfig = TrainingConfig()
    batch_size: int = 8
    hidden_size: int = 8
    protocol_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.qwen, FrozenObject) or not isinstance(self.training, TrainingConfig):
            raise BoundaryError("feature_job", "untyped_spec")
        for name in ("batch_size", "hidden_size"):
            if unsigned(getattr(self, name), f"feature_job.{name}") == 0:
                raise BoundaryError("feature_job", "zero_dimension")
        if self.batch_size > 1024 or self.hidden_size > 65536:
            raise BoundaryError("feature_job", "dimension_limit")
        if self.protocol_id is not None:
            digest(self.protocol_id, "feature_job.protocol_id")
        if self.training.purpose == "research" and self.protocol_id is None:
            raise BoundaryError("feature_job", "frozen_protocol_required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "qwen": self.qwen.value(),
            "training": self.training.to_dict(),
            "batch_size": self.batch_size,
            "hidden_size": self.hidden_size,
            "protocol_id": self.protocol_id,
        }

    @classmethod
    def decode(cls, value: object) -> FeatureJobSpec:
        obj = object_fields(value, set(cls.__dataclass_fields__), "feature_job.spec")
        return cls(
            FrozenObject.of(obj["qwen"]), TrainingConfig.decode(obj["training"]),
            obj["batch_size"], obj["hidden_size"], obj["protocol_id"],
        )


def publish_feature_job(
    store: ArtifactStore, view_id: str, runtime: Producer, spec: FeatureJobSpec
) -> Manifest:
    view, _ = load_model_view(store, view_id)
    validate_qwen_identity(spec.qwen, view.parameters.value()["scope"])
    parents = [Parent("model_view", view_id)]
    if spec.protocol_id is not None:
        parents.append(Parent("protocol", spec.protocol_id))
    job = Manifest(
        "feature_job", runtime, tuple(parents),
        parameters=FrozenObject.of({"schema": FEATURE_JOB_SCHEMA, "spec": spec.to_dict()}),
    )
    store.publish(job)
    return job


def load_feature_job(
    store: ArtifactStore, job_id: str, runtime: Producer
) -> tuple[Manifest, FeatureJobSpec]:
    job = store.get_manifest(job_id)
    obj = object_fields(job.parameters.value(), {"schema", "spec"}, "feature_job")
    if job.kind != "feature_job" or job.producer != runtime or obj["schema"] != FEATURE_JOB_SCHEMA:
        raise BoundaryError("feature_job", "source_lock_or_schema_mismatch")
    spec = FeatureJobSpec.decode(obj["spec"])
    expected = ["model_view"] + (["protocol"] if spec.protocol_id is not None else [])
    if job.payloads or sorted(p.role for p in job.parents) != expected:
        raise BoundaryError("feature_job", "inventory_mismatch")
    if spec.protocol_id is not None and job.parent("protocol") != spec.protocol_id:
        raise BoundaryError("feature_job", "protocol_mismatch")
    view, _ = load_model_view(store, job.parent("model_view"))
    validate_qwen_identity(spec.qwen, view.parameters.value()["scope"])
    return job, spec


@dataclass(frozen=True)
class ComputeRequest:
    kind: str
    input_id: str
    producer: Producer
    attempt_id: str
    resume: str | None = None
    stop_after: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"features", "training"}:
            raise BoundaryError("compute_request", "unknown_kind")
        digest(self.input_id, "compute_request.input_id")
        text(self.attempt_id, "compute_request.attempt_id", maximum=128)
        if not isinstance(self.producer, Producer):
            raise BoundaryError("compute_request", "untyped_producer")
        if self.resume is not None:
            digest(self.resume, "compute_request.resume")
        if self.stop_after is not None and unsigned(self.stop_after, "compute.stop_after") == 0:
            raise BoundaryError("compute_request", "zero_pause_budget")
        if self.kind == "features" and (self.resume is not None or self.stop_after is not None):
            raise BoundaryError("compute_request", "feature_resume_not_supported")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": REQUEST_SCHEMA, **asdict(self)}

    @property
    def request_id(self) -> str:
        return semantic_hash(self.to_dict())

    @classmethod
    def decode(cls, value: object) -> ComputeRequest:
        obj = dict(object_fields(value, {"schema", *cls.__dataclass_fields__}, "compute_request"))
        if obj.pop("schema") != REQUEST_SCHEMA:
            raise BoundaryError("compute_request", "unsupported_schema")
        obj["producer"] = Producer.decode(obj["producer"])
        return cls(**obj)


@dataclass(frozen=True)
class ComputeReceipt:
    request_id: str
    attempt_id: str
    kind: str
    input_id: str
    producer: Producer
    state: str
    output_id: str | None
    checkpoint_id: str | None = None

    def __post_init__(self) -> None:
        digest(self.request_id, "compute_receipt.request_id")
        ComputeRequest(self.kind, self.input_id, self.producer, self.attempt_id)
        if self.state not in {"candidate_prepared", "paused"}:
            raise BoundaryError("compute_receipt", "unknown_state")
        for value in (self.output_id, self.checkpoint_id):
            if value is not None:
                digest(value, "compute_receipt.output")
        if (self.state == "candidate_prepared") != (self.output_id is not None):
            raise BoundaryError("compute_receipt", "state_output_mismatch")
        if self.state == "paused" and (self.kind != "training" or self.checkpoint_id is None):
            raise BoundaryError("compute_receipt", "pause_checkpoint_required")
        if self.kind == "features" and self.checkpoint_id is not None:
            raise BoundaryError("compute_receipt", "unexpected_checkpoint")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": RECEIPT_SCHEMA, **asdict(self)}

    def bind(self, request: ComputeRequest) -> None:
        if (
            self.request_id != request.request_id or self.attempt_id != request.attempt_id
            or self.kind != request.kind or self.input_id != request.input_id
            or self.producer != request.producer
        ):
            raise BoundaryError("compute_receipt", "request_binding_mismatch")

    @classmethod
    def decode(cls, value: object) -> ComputeReceipt:
        obj = dict(object_fields(value, {"schema", *cls.__dataclass_fields__}, "compute_receipt"))
        if obj.pop("schema") != RECEIPT_SCHEMA:
            raise BoundaryError("compute_receipt", "unsupported_schema")
        obj["producer"] = Producer.decode(obj["producer"])
        return cls(**obj)
