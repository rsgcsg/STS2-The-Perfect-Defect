"""Clean-source CPU subprocess qualification of the disposable compute pipeline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from ..fullrun.data import admit, publish_dataset, publish_source
from ..fullrun.features import publish_model_view
from ..fullrun.fixtures import SyntheticSourceAdapter, synthetic_bundle
from ..fullrun.representation import FullRunSerializer
from ..json_boundary import BoundaryError, FrozenObject, decode_json, json_bytes
from ..qwen.fake_backend import DeterministicFakeQwenBackend
from ..workbench.control import open_store, source_identity
from ..workers.contracts import TrainingConfig
from .contracts import ComputeReceipt, ComputeRequest, FeatureJobSpec, publish_feature_job
from .execution import prepare_feature_run, validate_receipt


def run_smoke(root: Path) -> dict:
    runtime = source_identity(root)
    with tempfile.TemporaryDirectory(prefix="stpd-cloud-cpu-") as directory:
        path = Path(directory)
        store = open_store(str(path / "store"))
        source, projection = publish_source(
            store, synthetic_bundle(runs=6), SyntheticSourceAdapter(), runtime
        )
        dataset = publish_dataset(store, admit((projection,)), (source,), runtime)
        view = publish_model_view(store, dataset.artifact_id, FullRunSerializer(), runtime)
        spec = FeatureJobSpec(
            FrozenObject.of(asdict(DeterministicFakeQwenBackend(8).identity)),
            TrainingConfig(max_steps=3, checkpoint_interval=1),
        )
        job = publish_feature_job(store, view.artifact_id, runtime, spec)

        def execute(request: ComputeRequest) -> ComputeReceipt:
            request_path = path / (request.attempt_id + ".json")
            request_path.write_bytes(json_bytes(request.to_dict()))
            result = subprocess.run(
                [sys.executable, "-m", "stpd.cloud_jobs", "--request", str(request_path),
                 "--store", str(path / "store")],
                cwd=root, capture_output=True, text=True, check=False, timeout=180,
            )
            if result.returncode:
                raise BoundaryError("cloud_smoke", "child_failed_inspect_compute_events")
            receipt = ComputeReceipt.decode(decode_json(result.stdout))
            validate_receipt(store, request, receipt)
            return receipt

        feature = execute(ComputeRequest("features", job.artifact_id, runtime, "features"))
        assert feature.output_id is not None
        pipeline = prepare_feature_run(store, job.artifact_id, feature.output_id, runtime)
        paused = execute(ComputeRequest(
            "training", pipeline.run_id, runtime, "pause", stop_after=1
        ))
        if paused.state != "paused" or paused.checkpoint_id is None:
            raise BoundaryError("cloud_smoke", "pause_checkpoint_missing")
        resumed = execute(ComputeRequest(
            "training", pipeline.run_id, runtime, "resume", resume=paused.checkpoint_id
        ))
        full = execute(ComputeRequest("training", pipeline.run_id, runtime, "uninterrupted"))
        assert resumed.output_id is not None and full.output_id is not None
        resumed_result, full_result = (
            store.get_manifest(resumed.output_id), store.get_manifest(full.output_id)
        )
        resumed_model = store.get_manifest(resumed_result.parent("model"))
        full_model = store.get_manifest(full_result.parent("model"))
        if (
            store.bytes(resumed_model.payload("weights"))
            != store.bytes(full_model.payload("weights"))
            or resumed_result.parameters != full_result.parameters
            or store.get_manifest(resumed_result.parent("offline_evaluation")).parameters
            != store.get_manifest(full_result.parent("offline_evaluation")).parameters
        ):
            raise BoundaryError("cloud_smoke", "resume_weights_or_evaluation_mismatch")
        if store.blobs.keys("run-completions/"):
            raise BoundaryError("cloud_smoke", "worker_selected_hub_completion")
        if source_identity(root) != runtime:
            raise BoundaryError("cloud_smoke", "source_changed_during_execution")
        # Checkpoint audit RNG bytes can differ by process. We compare learned
        # weights/steps/evaluation, never rewrite that audit state to force equal IDs.
        return {
            "schema": "stpd/cloud-worker-cpu-e2e-v1", "producer": runtime.to_dict(),
            "feature_job_id": job.artifact_id, "feature_set_id": feature.output_id,
            "run_id": pipeline.run_id, "checkpoint_id": paused.checkpoint_id,
            "result_id": resumed.output_id, "replacement_process_resume": "PASS",
            "learned_weights_match_uninterrupted": "PASS",
            "dev_metrics_match_uninterrupted": "PASS", "completion_slot_selected": False,
            "real_cloud": "NOT_RUN", "scope": "synthetic_cpu_engineering",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_smoke(Path(__file__).resolve().parents[2])
    raw = json_bytes(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(raw)
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
