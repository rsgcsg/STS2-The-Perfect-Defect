from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import torch

from stpd.artifact_contracts import Manifest, Producer
from stpd.fullrun.features import compile_features, load_features
from stpd.json_boundary import BoundaryError, FrozenObject
from stpd.qwen.fake_backend import DeterministicFakeQwenBackend
from stpd.storage.blobs import StoreError
from stpd.storage.run_reporter import ObjectStoreRunReporter
from stpd.workers.contracts import TrainingConfig, load_training_input, prepare_run, prepare_training_input
from stpd.workers.ranking import RankingEngine, load_head
from stpd.workers.worker import WorkerExecutionError, execute

from test_artifact_store_v1 import PRODUCER
from test_fullrun_features import prepared


def training(tmp_path: Path, *, head: str = "linear"):
    store, _, view = prepared(tmp_path)
    feature = compile_features(store, view.artifact_id, DeterministicFakeQwenBackend(8), PRODUCER)
    config = TrainingConfig(seed=41, max_steps=4, checkpoint_interval=2, head=head)
    envelope = prepare_training_input(store, feature.artifact_id, PRODUCER, config)
    reporter = ObjectStoreRunReporter(store, store.blobs)
    return store, reporter, envelope, config


@pytest.mark.parametrize("head", ["linear", "mlp"])
def test_crash_resume_matches_uninterrupted_head_and_keeps_qwen_frozen(tmp_path: Path, head: str) -> None:
    store, reporter, envelope, config = training(tmp_path, head=head)
    _, first_run = prepare_run(store, envelope.artifact_id, PRODUCER, replicate="uninterrupted")
    first = execute(store, reporter, first_run.artifact_id, PRODUCER)
    assert first.state == "completed"
    first_result = store.get_manifest(first.result_id)
    first_model = store.get_manifest(first_result.parent("model"))
    _, resumed_run = prepare_run(store, envelope.artifact_id, PRODUCER, replicate="resumed")
    paused = execute(store, reporter, resumed_run.artifact_id, PRODUCER, stop_after=1)
    assert paused.state == "paused" and paused.checkpoint_id
    assert reporter.completed(resumed_run.artifact_id) is None
    resumed = execute(store, reporter, resumed_run.artifact_id, PRODUCER, resume=paused.checkpoint_id)
    resumed_result = store.get_manifest(resumed.result_id)
    resumed_model = store.get_manifest(resumed_result.parent("model"))
    assert store.bytes(first_model.payload("weights")) == store.bytes(resumed_model.payload("weights"))
    assert execute(store, reporter, resumed_run.artifact_id, PRODUCER).result_id == resumed.result_id
    model = load_head(store.bytes(first_model.payload("weights")), 8, config)
    assert all(bool(torch.isfinite(parameter).all()) for parameter in model.parameters())
    engine = RankingEngine(load_features(store, envelope.parent("feature_set")), config)
    engine.advance()
    assert engine.matrix.grad is None and not engine.matrix.requires_grad
    events = reporter.events(resumed_run.artifact_id)
    assert {event.parameters.value()["kind"] for event in events} >= {"paused", "resumed", "checkpoint"}
    evaluation = store.get_manifest(resumed_result.parent("offline_evaluation"))
    assert evaluation.parameters.value()["partition"] == "dev"
    assert evaluation.parameters.value()["scientific_verdict"] == "not_claimed"


def test_input_source_lock_qwen_and_resume_identity_drift_rejected(tmp_path: Path) -> None:
    store, reporter, envelope, config = training(tmp_path)
    wrong_source = Producer(PRODUCER.repository, "c" * 40, PRODUCER.uv_lock_sha256)
    with pytest.raises(BoundaryError, match="source_lock"):
        load_training_input(store, envelope.artifact_id, wrong_source)
    altered = envelope.parameters.value()
    altered["qwen"]["model_revision"] = "changed"
    forged = replace(envelope, parameters=FrozenObject.of(altered))
    store.publish(forged)
    with pytest.raises(BoundaryError, match="lineage"):
        load_training_input(store, forged.artifact_id, PRODUCER)
    _, run1 = prepare_run(store, envelope.artifact_id, PRODUCER, replicate="first")
    _, run2 = prepare_run(store, envelope.artifact_id, PRODUCER, replicate="second")
    pause = execute(store, reporter, run1.artifact_id, PRODUCER, stop_after=1)
    with pytest.raises(WorkerExecutionError, match="resume_identity"):
        execute(store, reporter, run2.artifact_id, PRODUCER, resume=pause.checkpoint_id)
    assert reporter.completed(run2.artifact_id) is None
    assert any(e.parameters.value()["kind"] == "attempt_failed" for e in reporter.events(run2.artifact_id))
    with pytest.raises(BoundaryError, match="frozen_protocol"):
        prepare_training_input(store, envelope.parent("feature_set"), PRODUCER,
                               replace(config, purpose="research"))


def test_checkpoint_report_failure_is_not_completion_and_can_resume(tmp_path: Path) -> None:
    store, reporter, envelope, _ = training(tmp_path)
    _, run = prepare_run(store, envelope.artifact_id, PRODUCER)

    class FailsOnce(ObjectStoreRunReporter):
        failed = False

        def emit(self, event: Manifest) -> str:
            if event.parameters.value()["kind"] == "checkpoint" and not self.failed:
                self.failed = True
                raise StoreError("injected_reporting_failure")
            return super().emit(event)

    failing = FailsOnce(store, store.blobs)
    with pytest.raises(WorkerExecutionError) as caught:
        execute(store, failing, run.artifact_id, PRODUCER, stop_after=1)
    assert caught.value.failure_durable
    assert reporter.completed(run.artifact_id) is None
    saved = [store.get_manifest(i) for i in store.manifest_ids()
             if store.get_manifest(i).kind == "checkpoint"]
    assert len(saved) == 1
    result = execute(store, reporter, run.artifact_id, PRODUCER, resume=saved[0].artifact_id)
    assert result.state == "completed"


def test_checkpoint_model_and_permutation_contract(tmp_path: Path) -> None:
    store, _, envelope, config = training(tmp_path)
    features = load_features(store, envelope.parent("feature_set"))
    canonical = RankingEngine(features, config)
    permuted = RankingEngine(features, replace(config, candidate_order="permuted"))
    canonical.advance()
    permuted.advance()
    for left, right in zip(canonical.head.parameters(), permuted.head.parameters(), strict=True):
        torch.testing.assert_close(left, right)
    raw = canonical.checkpoint()
    wrong = RankingEngine(features, replace(config, seed=config.seed + 1))
    with pytest.raises(BoundaryError, match="resume_identity"):
        wrong.restore(raw)
    restored = RankingEngine(features, config)
    restored.restore(raw)
    assert restored.step == canonical.step
    assert restored.model_bytes() == canonical.model_bytes()
