"""Dispatch to existing feature/training owners without granting final Hub authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Protocol

from ..artifact_contracts import Manifest, Producer
from ..contracts import QwenBackend
from ..fullrun.evaluation import load_evaluation
from ..fullrun.features import compile_features, load_features
from ..json_boundary import BoundaryError, FrozenObject
from ..storage.store import ArtifactStore
from ..workers.contracts import load_training_input, prepare_run, prepare_training_input
from ..workers.worker import CHECKPOINT_SCHEMA, MODEL_SCHEMA, execute
from .contracts import ComputeReceipt, ComputeRequest, load_feature_job


class FeatureBackend(QwenBackend, Protocol):
    hidden_size: int


class CandidateReporter:
    """Persist candidates/events, never select a shared completion or grant a lease.

    A stale or preempted attempt may leave immutable diagnostic artifacts. Only the
    Hub's transactional attempt/fence check may accept a returned receipt.
    """

    def __init__(
        self, store: ArtifactStore, run_id: str, runtime: Producer,
        *, request: ComputeRequest | None = None,
    ) -> None:
        self.store, self.run_id, self.runtime = store, run_id, runtime
        if request is not None and (
            request.kind != "training" or request.input_id != run_id or request.producer != runtime
        ):
            raise BoundaryError("candidate_reporter", "request_binding_mismatch")
        self.request = request

    def _bound(self, manifest: Manifest, kind: str) -> None:
        if (
            manifest.kind != kind or manifest.parent("run") != self.run_id
            or manifest.producer != self.runtime
        ):
            raise BoundaryError("candidate_reporter", "foreign_run_or_source")

    def emit(self, event: Manifest) -> str:
        self._bound(event, "run_event")
        if event.parameters.value().get("schema") != "stpd/run-event-v1":
            raise BoundaryError("candidate_reporter", "unsupported_event")
        if self.request is not None:
            parameters = event.parameters.value()
            details = dict(parameters.get("details", {}))
            details.update({
                "compute_request_id": self.request.request_id,
                "compute_attempt_id": self.request.attempt_id,
            })
            parameters["details"] = details
            event = replace(event, parameters=FrozenObject.of(parameters))
        return self.store.publish(event)

    def completed(self, run_id: str) -> Manifest | None:
        if run_id != self.run_id:
            raise BoundaryError("candidate_reporter", "foreign_run")
        return None

    def complete(self, result: Manifest) -> str:
        self._bound(result, "run_result")
        if result.parameters.value().get("schema") != "stpd/run-result-v1":
            raise BoundaryError("candidate_reporter", "unsupported_result")
        return self.store.publish(result)

    def events(self, run_id: str) -> tuple[Manifest, ...]:
        if run_id != self.run_id:
            raise BoundaryError("candidate_reporter", "foreign_run")
        return tuple(
            value for identity in self.store.manifest_ids()
            if (value := self.store.get_manifest(identity)).kind == "run_event"
            and value.producer == self.runtime
            and any(p.role == "run" and p.artifact_id == run_id for p in value.parents)
        )


def execute_feature_job(
    store: ArtifactStore, job_id: str, runtime: Producer, backend: FeatureBackend
) -> Manifest:
    job, spec = load_feature_job(store, job_id, runtime)
    if asdict(backend.identity) != spec.qwen.value() or backend.hidden_size != spec.hidden_size:
        raise BoundaryError("feature_job", "backend_identity_or_dimension_mismatch")
    return compile_features(
        store, job.parent("model_view"), backend, runtime, batch_size=spec.batch_size
    )


def validate_feature_output(
    store: ArtifactStore, job_id: str, feature_id: str, runtime: Producer
) -> Manifest:
    job, spec = load_feature_job(store, job_id, runtime)
    features = load_features(store, feature_id)
    if (
        features.manifest.producer != runtime
        or features.view.artifact_id != job.parent("model_view")
        or features.manifest.parameters.value().get("qwen") != spec.qwen.value()
        or features.matrix.shape[1] != spec.hidden_size
    ):
        raise BoundaryError("feature_job", "feature_output_mismatch")
    return features.manifest


@dataclass(frozen=True)
class PreparedFeatureRun:
    feature_job_id: str
    feature_set_id: str
    training_input_id: str
    experiment_id: str
    run_id: str


def prepare_feature_run(
    store: ArtifactStore, job_id: str, feature_id: str, runtime: Producer,
    *, replicate: str = "primary",
) -> PreparedFeatureRun:
    _, spec = load_feature_job(store, job_id, runtime)
    validate_feature_output(store, job_id, feature_id, runtime)
    training = prepare_training_input(
        store, feature_id, runtime, spec.training, protocol_id=spec.protocol_id
    )
    experiment, run = prepare_run(store, training.artifact_id, runtime, replicate=replicate)
    return PreparedFeatureRun(
        job_id, feature_id, training.artifact_id, experiment.artifact_id, run.artifact_id
    )


def dispatch(
    store: ArtifactStore, request: ComputeRequest, runtime: Producer,
    *, backend: FeatureBackend | None = None,
) -> ComputeReceipt:
    if request.producer != runtime:
        raise BoundaryError("compute", "runtime_source_lock_mismatch")
    if request.kind == "features":
        if backend is None:
            raise BoundaryError("compute", "feature_backend_required")
        features = execute_feature_job(store, request.input_id, runtime, backend)
        return ComputeReceipt(
            request.request_id, request.attempt_id, request.kind, request.input_id,
            runtime, "candidate_prepared", features.artifact_id,
        )
    if backend is not None:
        raise BoundaryError("compute", "training_must_use_frozen_features")
    result = execute(
        store, CandidateReporter(store, request.input_id, runtime, request=request),
        request.input_id, runtime,
        resume=request.resume, stop_after=request.stop_after,
    )
    return ComputeReceipt(
        request.request_id, request.attempt_id, request.kind, request.input_id, runtime,
        "candidate_prepared" if result.state == "completed" else "paused",
        result.result_id, result.checkpoint_id,
    )


def _checkpoint(
    store: ArtifactStore, checkpoint_id: str, run_id: str, training_id: str, runtime: Producer
) -> Manifest:
    checkpoint = store.get_manifest(checkpoint_id)
    if (
        checkpoint.kind != "checkpoint" or checkpoint.producer != runtime
        or checkpoint.parameters.value().get("schema") != CHECKPOINT_SCHEMA
        or sorted(p.role for p in checkpoint.parents) != ["run", "training_input"]
        or checkpoint.parent("run") != run_id
        or checkpoint.parent("training_input") != training_id
        or {p.role for p in checkpoint.payloads} != {"checkpoint"}
    ):
        raise BoundaryError("compute_receipt", "checkpoint_binding_mismatch")
    for _ in store.read_payload(checkpoint.payload("checkpoint")):
        pass
    return checkpoint


def validate_receipt(
    store: ArtifactStore, request: ComputeRequest, receipt: ComputeReceipt
) -> None:
    """CPU-side binding/integrity admission; not a replay or a scientific verdict.

    Validate before the Hub's atomic fenced selection. Worker training admission and
    checkpoint resume continue to perform their stronger device/optimizer validation.
    """
    receipt.bind(request)
    runtime = request.producer
    if request.kind == "features":
        if receipt.output_id is None:
            raise BoundaryError("compute_receipt", "missing_feature_output")
        validate_feature_output(store, request.input_id, receipt.output_id, runtime)
        return
    run = store.get_manifest(request.input_id)
    if run.kind != "run" or run.producer != runtime:
        raise BoundaryError("compute_receipt", "run_identity_mismatch")
    training, config, features = load_training_input(
        store, run.parent("training_input"), runtime
    )
    if receipt.checkpoint_id is not None:
        _checkpoint(store, receipt.checkpoint_id, run.artifact_id, training.artifact_id, runtime)
    if receipt.state == "paused":
        return
    if receipt.output_id is None:
        raise BoundaryError("compute_receipt", "missing_result")
    result = store.get_manifest(receipt.output_id)
    roles = [
        "baseline_action_only", "baseline_uniform_legal", "model", "offline_evaluation",
        "run", "training_input",
    ]
    if (
        result.kind != "run_result" or result.producer != runtime
        or result.parameters.value().get("schema") != "stpd/run-result-v1"
        or result.parameters.value().get("state") != "completed"
        or sorted(p.role for p in result.parents) != roles
        or result.parent("run") != request.input_id
        or result.parent("training_input") != training.artifact_id
    ):
        raise BoundaryError("compute_receipt", "result_binding_mismatch")
    model = store.get_manifest(result.parent("model"))
    info = model.parameters.value()
    if (
        model.kind != "model" or model.producer != runtime or info.get("schema") != MODEL_SCHEMA
        or sorted(p.role for p in model.parents)
        != ["checkpoint", "model_view", "run", "training_input"]
        or model.parent("run") != run.artifact_id
        or model.parent("training_input") != training.artifact_id
        or model.parent("model_view") != features.view.artifact_id
        or info.get("qwen") != training.parameters.value()["qwen"]
        or info.get("serializer") != training.parameters.value()["serializer"]
        or info.get("head") != config.head or info.get("dtype") != config.dtype
        or info.get("hidden_size") != features.matrix.shape[1]
        or {p.role for p in model.payloads} != {"weights"}
    ):
        raise BoundaryError("compute_receipt", "model_binding_mismatch")
    saved = _checkpoint(
        store, model.parent("checkpoint"), run.artifact_id, training.artifact_id, runtime
    )
    details = saved.parameters.value()
    if (
        details.get("step") != details.get("total_steps")
        or details.get("step") != info.get("steps")
        or details.get("step") != result.parameters.value().get("steps")
        or (receipt.checkpoint_id is not None and receipt.checkpoint_id != saved.artifact_id)
    ):
        raise BoundaryError("compute_receipt", "completion_step_mismatch")
    for _ in store.read_payload(model.payload("weights")):
        pass
    for role, baseline in (
        ("offline_evaluation", "model"), ("baseline_uniform_legal", "uniform_legal"),
        ("baseline_action_only", "action_only"),
    ):
        evaluation = load_evaluation(store, result.parent(role))
        if (
            evaluation.manifest.producer != runtime
            or evaluation.manifest.parent("model") != model.artifact_id
            or evaluation.manifest.parent("model_view") != features.view.artifact_id
            or evaluation.manifest.parameters.value().get("partition") != "dev"
            or evaluation.manifest.parameters.value().get("baseline") != baseline
        ):
            raise BoundaryError("compute_receipt", "evaluation_binding_mismatch")
