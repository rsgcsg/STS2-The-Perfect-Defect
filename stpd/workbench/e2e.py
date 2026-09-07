"""Clean-checkout CPU qualification with durable transfer and a replacement worker process."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..fullrun.data import admit, load_dataset, publish_dataset, publish_source
from ..fullrun.features import compile_features, publish_model_view
from ..fullrun.fixtures import SyntheticSourceAdapter, synthetic_bundle
from ..fullrun.representation import FullRunSerializer
from ..json_boundary import BoundaryError
from ..qwen.fake_backend import DeterministicFakeQwenBackend
from ..storage.registry import SQLiteRegistry, sync_registry
from ..storage.store import copy_artifact
from ..workers.contracts import TrainingConfig, prepare_run, prepare_training_input
from .control import doctor, open_store, source_identity


def _worker(root: Path, store: Path, run: str, *options: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "stpd.workbench",
            "worker",
            "--store",
            str(store),
            "--run",
            run,
            "--root",
            str(root),
            *options,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise BoundaryError("e2e", "worker_subprocess_failed")
    result = json.loads(completed.stdout)
    if not isinstance(result, dict):
        raise BoundaryError("e2e", "worker_result_not_object")
    return result


def run_e2e(root: Path) -> dict[str, Any]:
    runtime = source_identity(root)
    with tempfile.TemporaryDirectory(prefix="stpd-cpu-e2e-") as temporary:
        local = Path(temporary)
        store = open_store(str(local / "origin"))
        source, projection = publish_source(
            store, synthetic_bundle(runs=6, seed=17), SyntheticSourceAdapter(), runtime
        )
        # Exercise actual deduplication rather than merely asserting fixture uniqueness.
        admitted = admit((projection, projection), seed=23)
        if admitted.exact_duplicates != len(projection.transitions):
            raise BoundaryError("e2e", "dedup_failed")
        dataset = publish_dataset(store, admitted, (source,), runtime)
        view = publish_model_view(store, dataset.artifact_id, FullRunSerializer(), runtime)
        features = compile_features(
            store, view.artifact_id, DeterministicFakeQwenBackend(8), runtime
        )
        outcomes = []
        for head in ("linear", "mlp"):
            config = TrainingConfig(seed=41, max_steps=4, checkpoint_interval=2, head=head)
            training = prepare_training_input(store, features.artifact_id, runtime, config)
            _, run = prepare_run(store, training.artifact_id, runtime)
            paused = _worker(root, local / "origin", run.artifact_id, "--stop-after", "1")
            if paused.get("state") != "paused" or not paused.get("checkpoint_id"):
                raise BoundaryError("e2e", "worker_did_not_pause")
            # Durable remote-like transfer, then a new OS process resumes without old memory.
            replacement_path = local / ("replacement-" + head)
            replacement = open_store(str(replacement_path))
            copy_artifact(store, replacement, str(paused["checkpoint_id"]))
            finished = _worker(
                root, replacement_path, run.artifact_id, "--resume", str(paused["checkpoint_id"])
            )
            if finished.get("state") != "completed" or not finished.get("result_id"):
                raise BoundaryError("e2e", "resume_did_not_complete")
            duplicate = _worker(root, replacement_path, run.artifact_id)
            if duplicate.get("result_id") != finished["result_id"]:
                raise BoundaryError("e2e", "duplicate_completion_drift")
            copy_artifact(replacement, store, str(finished["result_id"]))
            # Transfer events too: these are durable evidence, not authority from filenames.
            for identity in replacement.manifest_ids():
                copy_artifact(replacement, store, identity)
            outcomes.append(
                {
                    "head": head,
                    "run_id": run.artifact_id,
                    "checkpoint_id": paused["checkpoint_id"],
                    "result_id": finished["result_id"],
                }
            )
        registry_path = local / "registry.sqlite"
        registry = SQLiteRegistry(registry_path)
        count = sync_registry(store, registry)
        before = tuple(m.artifact_id for m in registry.manifests())
        registry_path.unlink()
        rebuilt = SQLiteRegistry(registry_path)
        if sync_registry(store, rebuilt) != count:
            raise BoundaryError("e2e", "registry_rebuild_count")
        if tuple(m.artifact_id for m in rebuilt.manifests()) != before:
            raise BoundaryError("e2e", "registry_rebuild_identity")
        peer = open_store(str(local / "sync"))
        for identity in store.manifest_ids():
            copy_artifact(store, peer, identity)
        load_dataset(peer, dataset.artifact_id)
        integrity = doctor(peer)
        projections = qualify_projections(peer, rebuilt)
        from ..fullrun.campaign import default_harness_config
        from ..fullrun.gold import GoldAnnotation
        from ..fullrun.gold_store import gold_report, load_tasks, publish_labels, publish_tasks

        task_manifest = publish_tasks(
            peer, dataset.artifact_id, runtime, gold_split="gold_test", count=2
        )
        _, tasks = load_tasks(peer, task_manifest.artifact_id)
        task = tasks[0]
        annotation = GoldAnnotation(
            "e2e-fixture",
            task.task_id,
            "synthetic-annotator",
            task.gold_split,
            task.action_keys,
            task.candidate_display_order,
            "accepted",
            task.action_keys,
            task.action_keys[0],
            1.0,
            "synthetic_fixture",
            state_hash=task.state_hash,
        )
        labels = publish_labels(
            peer, task_manifest.artifact_id, (annotation,), runtime, allow_synthetic=True
        )
        gold = gold_report(peer, labels.artifact_id)
        if gold["coverage"] != 0.5 or "acceptable_overlap" in gold:
            raise BoundaryError("e2e", "sealed_gold_coverage_boundary")
        try:
            gold_report(peer, labels.artifact_id, mode="tuning")
        except BoundaryError as error:
            if error.code != "sealed_test_protocol_required":
                raise
        else:
            raise BoundaryError("e2e", "sealed_gold_tuning_leak")
        default_harness_config().validate()
        return {
            "schema": "stpd/cpu-e2e-v1",
            "producer": runtime.to_dict(),
            "verdict": "CPU_E2E_PASS",
            "scope": "synthetic_engineering",
            "records": len(admitted.records),
            "deduplicated": admitted.exact_duplicates,
            "whole_runs": len(admitted.splits.value()),
            "dataset_id": dataset.artifact_id,
            "model_view_id": view.artifact_id,
            "feature_set_id": features.artifact_id,
            "workers": outcomes,
            "replacement_process_resume": "PASS",
            "registry_deleted_and_rebuilt": "PASS",
            "sync": integrity,
            "projections": projections,
            "gold_tooling": "SYNTHETIC_FIXTURE_PASS",
            "e0_e7_config": "PASS",
            "non_claims": [
                "Platform qualified data",
                "Human Gold",
                "real Qwen",
                "GPU",
                "real S3",
                "model quality",
                "live STS2",
            ],
        }


def qualify_projections(store: Any, registry: Any) -> dict[str, Any]:
    from .analysis import analyze
    from .dashboard import SECTIONS, project, render_html
    from .readiness import readiness

    analysis = analyze(registry, store)
    dashboard = project(registry, store, analysis=analysis)
    html = render_html(dashboard)
    if not all(name in dashboard.to_dict()["sections"] for name in SECTIONS):
        raise BoundaryError("e2e", "dashboard_section_missing")
    if not dashboard.to_dict()["sections"]["Lineage"] or "STPD Local Workbench" not in html:
        raise BoundaryError("e2e", "dashboard_lineage_missing")
    if analysis.to_dict()["metrics"]["top1"]["status"] != "present":
        raise BoundaryError("e2e", "duckdb_metrics_missing")
    pending = readiness(Path(__file__).resolve().parents[2])
    if pending["verdict"] != "EVIDENCE_REQUIRED":
        raise BoundaryError("e2e", "readiness_claimed_without_ci_receipt")
    return {
        "duckdb": "PASS",
        "dashboard": "PASS",
        "lineage": "PASS",
        "readiness_without_ci_receipt": pending["verdict"],
    }
