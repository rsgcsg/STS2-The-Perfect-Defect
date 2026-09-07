from __future__ import annotations

from pathlib import Path

import pytest
from test_artifact_store_v1 import PRODUCER
from test_fullrun_worker import training

from stpd.artifact_contracts import Manifest
from stpd.json_boundary import BoundaryError, FrozenObject
from stpd.storage.registry import SQLiteRegistry, sync_registry
from stpd.workbench.analysis import analyze
from stpd.workbench.dashboard import SECTIONS, project, render_html
from stpd.workers.contracts import prepare_run
from stpd.workers.worker import execute


def fixture(tmp_path: Path):
    store, reporter, envelope, _ = training(tmp_path)
    _, run = prepare_run(store, envelope.artifact_id, PRODUCER)
    execute(store, reporter, run.artifact_id, PRODUCER)
    registry = SQLiteRegistry(tmp_path / "registry.sqlite")
    sync_registry(store, registry)
    return store, registry


def test_analysis_uses_verified_dataset_counts_and_exact_comparison_lineage(tmp_path: Path) -> None:
    store, registry = fixture(tmp_path)
    value = analyze(registry, store).to_dict()
    assert value["engine"]["name"] == "duckdb"
    assert value["metrics"]["top1"]["status"] == "present"
    assert value["distributions"]["decision"]["value"][0]["records"] == 72
    # Three evaluations do not triple the actual Dataset population.
    assert sum(r["count"] for r in value["distributions"]["surface"]["value"]) == 72
    comparisons = value["ablation"]["value"]
    assert {r["baseline"] for r in comparisons} == {"model", "uniform_legal", "action_only"}
    assert all(r["head"] == "linear" and r["records"] == 72 for r in comparisons)
    assert value["performance"]["latency_ms"]["status"] == "absent"
    assert value["distributions"]["tokens"]["value"]["tokenizer"] == "whitespace-v1"
    with pytest.raises(BoundaryError, match="not_indexed"):
        analyze(registry, store, artifact_ids=["0" * 64])


def test_recorded_performance_failure_and_html_escaping(tmp_path: Path) -> None:
    store, registry = fixture(tmp_path)
    for kind, parameters in (
        (
            "performance",
            {
                "latency_ms": 4.0,
                "vram_mb": 128.0,
                "throughput_samples_per_s": 2.0,
                "gpu_hours": 0.001,
            },
        ),
        (
            "run_event",
            {"kind": "attempt_failed", "details": {"stage": "checkpoint", "code": "fixture"}},
        ),
        ("analysis", {"note": "<script>", "path": "/private/fixture"}),
    ):
        store.publish(Manifest(kind, PRODUCER, parameters=FrozenObject.of(parameters)))
    sync_registry(store, registry)
    value = analyze(registry, store).to_dict()
    assert value["performance"]["latency_ms"]["value"]["mean"] == 4.0
    assert value["failures"]["value"]["by_stage"] == [{"stage": "checkpoint", "count": 1}]
    dashboard = project(registry, store)
    assert set(dashboard.to_dict()["sections"]) == set(SECTIONS)
    rendered = render_html(dashboard)
    assert "&lt;script&gt;" in rendered and "<script>" not in rendered
    assert "/private/fixture" not in rendered
