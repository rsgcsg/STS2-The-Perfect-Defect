from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import pytest
from test_artifact_store_v1 import PRODUCER
from test_fullrun_features import prepared

from stpd.cloud_jobs.contracts import (
    ComputeReceipt,
    ComputeRequest,
    FeatureJobSpec,
    load_feature_job,
    publish_feature_job,
)
from stpd.cloud_jobs.execution import (
    CandidateReporter,
    dispatch,
    prepare_feature_run,
    validate_receipt,
)
from stpd.fullrun.features import compile_features
from stpd.json_boundary import BoundaryError, FrozenObject
from stpd.qwen.fake_backend import DeterministicFakeQwenBackend
from stpd.storage.run_reporter import ObjectStoreRunReporter
from stpd.workers.contracts import TrainingConfig
from stpd.workers.worker import WorkerExecutionError


def job_fixture(tmp_path: Path):
    store, dataset, view = prepared(tmp_path)
    backend = DeterministicFakeQwenBackend(8)
    spec = FeatureJobSpec(
        FrozenObject.of(asdict(backend.identity)),
        TrainingConfig(seed=17, max_steps=3, checkpoint_interval=1),
    )
    job = publish_feature_job(store, view.artifact_id, PRODUCER, spec)
    request = ComputeRequest("features", job.artifact_id, PRODUCER, "features-attempt-1")
    return store, backend, spec, job, request


def test_cpu_controller_freezes_job_without_encoding_then_worker_publishes(tmp_path: Path) -> None:
    store, backend, spec, job, request = job_fixture(tmp_path)
    assert all(store.get_manifest(i).kind != "feature_set" for i in store.manifest_ids())
    assert FeatureJobSpec.decode(spec.to_dict()) == spec
    assert ComputeRequest.decode(request.to_dict()) == request
    receipt = dispatch(store, request, PRODUCER, backend=backend)
    raw_receipt = receipt.to_dict()
    assert ComputeReceipt.decode(raw_receipt) == receipt
    assert raw_receipt == receipt.to_dict()
    validate_receipt(store, request, receipt)
    assert receipt.state == "candidate_prepared" and receipt.output_id
    pipeline = prepare_feature_run(store, job.artifact_id, receipt.output_id, PRODUCER)
    assert pipeline.feature_job_id == job.artifact_id
    assert store.get_manifest(pipeline.training_input_id).parameters.value()["config"] == (
        spec.training.to_dict()
    )
    full_request = ComputeRequest("training", pipeline.run_id, PRODUCER, "train-full")
    finished = dispatch(store, full_request, PRODUCER)
    validate_receipt(store, full_request, finished)
    # The remote worker can prepare a candidate, but it cannot win a shared
    # completion slot. Hub lease/fence admission remains a separate transaction.
    assert ObjectStoreRunReporter(store, store.blobs).completed(pipeline.run_id) is None
    events = CandidateReporter(store, pipeline.run_id, PRODUCER).events(pipeline.run_id)
    assert all(
        event.parameters.value()["details"]["compute_request_id"] == full_request.request_id
        for event in events
    )
    assert finished.output_id
    result = store.get_manifest(finished.output_id)
    assert result.parent("training_input") == pipeline.training_input_id
    assert result.parameters.value()["scientific_verdict"] == "not_claimed"


def test_explicit_resume_retains_run_identity_and_matches_uninterrupted(tmp_path: Path) -> None:
    store, backend, _, job, request = job_fixture(tmp_path)
    features = dispatch(store, request, PRODUCER, backend=backend)
    pipeline = prepare_feature_run(store, job.artifact_id, features.output_id, PRODUCER)
    full_request = ComputeRequest("training", pipeline.run_id, PRODUCER, "uninterrupted")
    full = dispatch(store, full_request, PRODUCER)
    pause_request = replace(full_request, attempt_id="pause", stop_after=1)
    paused = dispatch(store, pause_request, PRODUCER)
    validate_receipt(store, pause_request, paused)
    assert paused.state == "paused" and paused.checkpoint_id
    resume_request = replace(full_request, attempt_id="replacement", resume=paused.checkpoint_id)
    resumed = dispatch(store, resume_request, PRODUCER)
    validate_receipt(store, resume_request, resumed)
    assert resumed.output_id == full.output_id
    with pytest.raises(BoundaryError, match="request_binding"):
        validate_receipt(store, full_request, resumed)
    foreign = prepare_feature_run(
        store, job.artifact_id, features.output_id, PRODUCER, replicate="foreign"
    )
    with pytest.raises(WorkerExecutionError, match="resume_identity"):
        dispatch(store, replace(resume_request, input_id=foreign.run_id), PRODUCER)


def test_source_qwen_dimensions_and_future_schema_fail_before_encoding(tmp_path: Path) -> None:
    store, backend, _, job, request = job_fixture(tmp_path)
    wrong_source = replace(PRODUCER, source_revision="c" * 40)
    with pytest.raises(BoundaryError, match="runtime_source_lock"):
        dispatch(store, request, wrong_source, backend=backend)
    with pytest.raises(BoundaryError, match="source_lock"):
        load_feature_job(store, job.artifact_id, wrong_source)
    with pytest.raises(BoundaryError, match="backend_identity_or_dimension"):
        dispatch(store, request, PRODUCER, backend=DeterministicFakeQwenBackend(9))
    backend.identity = replace(backend.identity, model_revision="tampered")
    with pytest.raises(BoundaryError, match="backend_identity_or_dimension"):
        dispatch(store, request, PRODUCER, backend=backend)
    with pytest.raises(BoundaryError, match="unsupported_schema"):
        ComputeRequest.decode({**request.to_dict(), "schema": "future"})
    with pytest.raises(BoundaryError, match="feature_resume_not_supported"):
        replace(request, resume="a" * 64)
    assert all(store.get_manifest(i).kind != "feature_set" for i in store.manifest_ids())


def test_feature_reuse_revalidates_expected_backend_and_output_bytes(tmp_path: Path) -> None:
    store, backend, _, job, request = job_fixture(tmp_path)
    wrong = compile_features(
        store, job.parent("model_view"), DeterministicFakeQwenBackend(9), PRODUCER
    )
    with pytest.raises(BoundaryError, match="feature_output_mismatch"):
        prepare_feature_run(store, job.artifact_id, wrong.artifact_id, PRODUCER)
    receipt = dispatch(store, request, PRODUCER, backend=backend)
    feature = store.get_manifest(receipt.output_id)
    index = store.blobs.root / "payload-indexes" / "v1"
    (index / f"{feature.payload('features').sha256}.json").unlink()
    with pytest.raises(BoundaryError, match="object_not_found"):
        validate_receipt(store, request, receipt)


def test_candidate_reporter_rejects_foreign_run_and_tampered_receipt(tmp_path: Path) -> None:
    store, backend, _, job, request = job_fixture(tmp_path)
    features = dispatch(store, request, PRODUCER, backend=backend)
    pipeline = prepare_feature_run(store, job.artifact_id, features.output_id, PRODUCER)
    training = ComputeRequest("training", pipeline.run_id, PRODUCER, "attempt")
    receipt = dispatch(store, training, PRODUCER)
    reporter = CandidateReporter(store, "a" * 64, PRODUCER)
    with pytest.raises(BoundaryError, match="foreign_run_or_source"):
        reporter.complete(store.get_manifest(receipt.output_id))
    result = store.get_manifest(receipt.output_id)
    params = result.parameters.value()
    params["steps"] += 1
    bad = replace(result, parameters=FrozenObject.of(params))
    store.publish(bad)
    with pytest.raises(BoundaryError, match="completion_step_mismatch"):
        validate_receipt(store, training, replace(receipt, output_id=bad.artifact_id))
