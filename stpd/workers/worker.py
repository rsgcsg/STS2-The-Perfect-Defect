"""Provider-neutral verified training, explicit resume, model/evaluation publication."""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass

from ..artifact_contracts import Manifest, Parent, Producer
from ..fullrun.evaluation import action_only_prior, evaluate_samples, publish_evaluation
from ..json_boundary import BoundaryError, FrozenObject, json_bytes, unsigned
from ..storage.store import ArtifactStore
from .contracts import RUN_SCHEMA, load_training_input
from .ranking import RankingEngine
from .reporting import RunReporter

CHECKPOINT_SCHEMA = "stpd/ranking-checkpoint-v1"
MODEL_SCHEMA = "stpd/scheme1-model-v1"


@dataclass(frozen=True)
class WorkerResult:
    state: str
    run_id: str
    checkpoint_id: str | None = None
    result_id: str | None = None


class WorkerExecutionError(BoundaryError):
    def __init__(self, cause_code: str, *, failure_durable: bool) -> None:
        self.failure_durable = failure_durable
        super().__init__("worker", cause_code, "inspect exact run evidence and explicitly resume")


def execute(
    store: ArtifactStore,
    reporter: RunReporter,
    run_id: str,
    runtime: Producer,
    *,
    resume: str | None = None,
    stop_after: int | None = None,
) -> WorkerResult:
    run = store.get_manifest(run_id)
    if (
        run.kind != "run"
        or run.producer != runtime
        or run.parameters.value().get("schema") != RUN_SCHEMA
    ):
        raise BoundaryError("worker", "run_source_or_schema_mismatch")
    if sorted(p.role for p in run.parents) != ["experiment", "training_input"]:
        raise BoundaryError("worker", "run_parent_inventory_mismatch")
    training, config, features = load_training_input(store, run.parent("training_input"), runtime)
    experiment = store.get_manifest(run.parent("experiment"))
    if (
        experiment.kind != "experiment"
        or experiment.producer != runtime
        or experiment.parent("training_input") != training.artifact_id
    ):
        raise BoundaryError("worker", "experiment_input_mismatch")
    if stop_after is not None:
        unsigned(stop_after, "worker.stop_after")
        if stop_after == 0:
            raise BoundaryError("worker", "zero_pause_budget")
    previous = reporter.completed(run_id)
    if previous is not None:
        if (
            previous.producer != runtime
            or previous.parent("training_input") != training.artifact_id
        ):
            raise BoundaryError("worker", "completed_input_mismatch")
        return WorkerResult("completed", run_id, result_id=previous.artifact_id)
    attempt = uuid.uuid4().hex
    engine = RankingEngine(features, config)
    checkpoint_id: str | None = None
    metrics: list[dict[str, float | int]] = []

    def event(kind: str, *, parents: tuple[Parent, ...] = (), details: dict | None = None) -> None:
        value = Manifest(
            "run_event",
            runtime,
            (Parent("run", run_id), *parents),
            parameters=FrozenObject.of(
                {
                    "schema": "stpd/run-event-v1",
                    "attempt": attempt,
                    "kind": kind,
                    "step": engine.step,
                    "details": details or {},
                }
            ),
        )
        reporter.emit(value)

    def checkpoint() -> str:
        nonlocal metrics
        payload = store.put_payload(
            "checkpoint", io.BytesIO(engine.checkpoint()), "application/vnd.stpd.tensor-tree"
        )
        saved = Manifest(
            "checkpoint",
            runtime,
            (Parent("run", run_id), Parent("training_input", training.artifact_id)),
            (payload,),
            FrozenObject.of(
                {
                    "schema": CHECKPOINT_SCHEMA,
                    "step": engine.step,
                    "total_steps": engine.total_steps,
                    "data_identity": engine.data_identity,
                }
            ),
        )
        store.publish(saved)
        segment = store.put_payload("metrics", io.BytesIO(json_bytes(metrics)), "application/json")
        evidence = Manifest(
            "run_event",
            runtime,
            (Parent("run", run_id), Parent("checkpoint", saved.artifact_id)),
            (segment,),
            FrozenObject.of(
                {
                    "schema": "stpd/run-event-v1",
                    "attempt": attempt,
                    "kind": "checkpoint",
                    "step": engine.step,
                    "details": {},
                }
            ),
        )
        reporter.emit(evidence)
        metrics = []
        return saved.artifact_id

    try:
        if resume is not None:
            saved = store.get_manifest(resume)
            info = saved.parameters.value()
            if (
                saved.kind != "checkpoint"
                or saved.producer != runtime
                or info.get("schema") != CHECKPOINT_SCHEMA
                or saved.parent("run") != run_id
                or saved.parent("training_input") != training.artifact_id
                or info.get("data_identity") != engine.data_identity
                or sorted(p.role for p in saved.parents) != ["run", "training_input"]
                or {p.role for p in saved.payloads} != {"checkpoint"}
            ):
                raise BoundaryError("worker", "resume_identity_mismatch")
            if saved.payload("checkpoint").size > 512 * 1024 * 1024:
                raise BoundaryError("worker", "checkpoint_size_limit")
            engine.restore(b"".join(store.read_payload(saved.payload("checkpoint"))))
            if engine.step != info.get("step") or engine.total_steps != info.get("total_steps"):
                raise BoundaryError("worker", "checkpoint_step_mismatch")
            checkpoint_id = resume
        event(
            "resumed" if resume else "started",
            parents=(Parent("checkpoint", resume),) if resume else (),
        )
        started_step = engine.step
        while engine.step < engine.total_steps:
            loss = engine.advance()
            metrics.append({"step": engine.step, "loss": loss})
            pause = stop_after is not None and engine.step - started_step >= stop_after
            if (
                engine.step % config.checkpoint_interval == 0
                or pause
                or engine.step == engine.total_steps
            ):
                checkpoint_id = checkpoint()
            if pause and engine.step < engine.total_steps:
                event(
                    "paused",
                    parents=(Parent("checkpoint", checkpoint_id),) if checkpoint_id else (),
                )
                return WorkerResult("paused", run_id, checkpoint_id)
        if checkpoint_id is None:
            checkpoint_id = checkpoint()
        weights = store.put_payload(
            "weights", io.BytesIO(engine.model_bytes()), "application/x-safetensors"
        )
        model = Manifest(
            "model",
            runtime,
            (
                Parent("run", run_id),
                Parent("training_input", training.artifact_id),
                Parent("checkpoint", checkpoint_id),
            ),
            (weights,),
            FrozenObject.of(
                {
                    "schema": MODEL_SCHEMA,
                    "head": config.head,
                    "hidden_size": int(features.matrix.shape[1]),
                    "steps": engine.step,
                    "qwen": training.parameters.value()["qwen"],
                    "serializer": training.parameters.value()["serializer"],
                    "scope": training.parameters.value()["scope"],
                    "dtype": config.dtype,
                    "scientific_verdict": "not_claimed",
                }
            ),
        )
        store.publish(model)
        rows, summary = evaluate_samples(features.samples, engine.scores, seed=config.seed)
        evaluation = publish_evaluation(
            store, model, features.view.artifact_id, rows, summary, runtime, partition="dev"
        )
        baselines = []
        prior = action_only_prior(features.samples)
        for name, scorer in (
            ("uniform_legal", lambda i: (0.0,) * len(features.rows[i])),
            ("action_only", lambda i: prior(features.samples[i])),
        ):
            baseline_rows, baseline_summary = evaluate_samples(
                features.samples, scorer, seed=config.seed
            )
            baselines.append(
                publish_evaluation(
                    store,
                    model,
                    features.view.artifact_id,
                    baseline_rows,
                    baseline_summary,
                    runtime,
                    partition="dev",
                    baseline=name,
                )
            )
        result = Manifest(
            "run_result",
            runtime,
            (
                Parent("run", run_id),
                Parent("training_input", training.artifact_id),
                Parent("model", model.artifact_id),
                Parent("offline_evaluation", evaluation.artifact_id),
                *(Parent("baseline", b.artifact_id) for b in baselines),
            ),
            parameters=FrozenObject.of(
                {
                    "schema": "stpd/run-result-v1",
                    "steps": engine.step,
                    "state": "completed",
                    "scientific_verdict": "not_claimed",
                }
            ),
        )
        store.publish(result)
        event("result_prepared", parents=(Parent("result", result.artifact_id),))
        reporter.complete(result)
        return WorkerResult("completed", run_id, checkpoint_id, result.artifact_id)
    except Exception as error:
        code = error.code if isinstance(error, BoundaryError) else type(error).__name__
        durable = False
        try:
            event("attempt_failed", details={"code": code})
            durable = True
        except Exception:
            pass
        raise WorkerExecutionError(code, failure_durable=durable) from error
