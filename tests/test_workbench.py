from __future__ import annotations

import io
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from stpd.artifact_contracts import Manifest, Parent, Producer
from stpd.json_boundary import FrozenObject
from stpd.storage.local import LocalBlobStore
from stpd.storage.registry import SQLiteRegistry, sync_registry
from stpd.storage.store import ManifestArtifactStore
from stpd.workbench.analysis import analyze
from stpd.workbench.dashboard import SECTIONS, project, render_html

PRODUCER = Producer("fixture", "a" * 40, "b" * 64)


def _parquet(rows: list[dict[str, object]]) -> bytes:
    handle = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows), handle, compression="zstd", version="2.6")
    return handle.getvalue()


def _fixture(
    tmp_path: Path, *, performance: bool = False
) -> tuple[ManifestArtifactStore, SQLiteRegistry, Manifest]:
    store = ManifestArtifactStore(LocalBlobStore(tmp_path / "objects"))
    dataset = Manifest(
        "dataset",
        PRODUCER,
        parameters=FrozenObject.of(
            {"schema": "fixture", "records": 2, "runs": 1, "scope": "engineering"}
        ),
    )
    store.publish(dataset)
    samples = b"\n".join(
        json.dumps(
            {
                "transition_id": f"t{index}",
                "run_id": "run-1",
                "split": "dev",
                "surface": "combat",
                "family": "choice",
                "state_text": "state <safe>",
                "action_texts": ["play card", "end turn"],
                "action_keys": ["a", "b"],
                "chosen_index": 0,
            },
            sort_keys=True,
        ).encode()
        for index in range(2)
    ) + b"\n"
    samples_payload = store.put_bytes("samples", samples, "application/x-ndjson")
    view = Manifest(
        "model_view",
        PRODUCER,
        parents=(Parent("dataset", dataset.artifact_id),),
        payloads=(samples_payload,),
        parameters=FrozenObject.of({"schema": "fixture-view"}),
    )
    store.publish(view)
    model = Manifest(
        "model",
        PRODUCER,
        parents=(Parent("model_view", view.artifact_id),),
        parameters=FrozenObject.of(
            {
                "scope": "engineering",
                "path": "/private/weights.safetensors",
                "danger": "<script>",
            }
        ),
    )
    store.publish(model)
    rows = [
        {
            "transition_id": "t0",
            "run_id": "run-1",
            "surface": "combat",
            "family": "choice",
            "split": "dev",
            "candidate_count": 2,
            "top1": 1.0,
            "mrr": 1.0,
            "nll": 0.1,
            "confidence": 0.9,
            "margin": 1.2,
        },
        {
            "transition_id": "t1",
            "run_id": "run-1",
            "surface": "event",
            "family": "choice",
            "split": "dev",
            "candidate_count": 3,
            "top1": 0.0,
            "mrr": 0.5,
            "nll": 0.7,
            "confidence": 0.3,
            "margin": 0.2,
        },
    ]
    metrics_payload = store.put_bytes("metrics", _parquet(rows), "application/vnd.apache.parquet")
    evaluation = Manifest(
        "offline_evaluation",
        PRODUCER,
        parents=(Parent("model", model.artifact_id), Parent("model_view", view.artifact_id)),
        payloads=(metrics_payload,),
        parameters=FrozenObject.of({"schema": "fixture-eval", "baseline": "model"}),
    )
    store.publish(evaluation)
    if performance:
        performance_manifest = Manifest(
            "performance",
            PRODUCER,
            parameters=FrozenObject.of(
                {"latency_ms": 4.0, "vram_mb": 128.0, "throughput_samples_per_s": 2.0}
            ),
        )
        store.publish(performance_manifest)
        failure = Manifest(
            "run_event",
            PRODUCER,
            parameters=FrozenObject.of(
                {"kind": "attempt_failed", "details": {"code": "provider_error"}}
            ),
        )
        store.publish(failure)
    registry = SQLiteRegistry(tmp_path / "registry.sqlite")
    sync_registry(store, registry)
    return store, registry, evaluation


def test_analysis_uses_duckdb_and_keeps_absent_metrics_explicit(tmp_path: Path) -> None:
    store, registry, evaluation = _fixture(tmp_path)
    report = analyze(store, registry, artifact_ids=[evaluation.artifact_id])
    value = report.to_dict()
    assert value["engine"]["name"] == "duckdb"
    assert value["metrics"]["top1"]["value"] == 0.5
    assert value["metrics"]["calibration"]["status"] == "present"
    assert value["distributions"]["surface"]["value"] == {"combat": 1, "event": 1}
    assert value["distributions"]["candidate_count"]["value"] == {"2": 1, "3": 1}
    assert value["distributions"]["tokens"]["value"]["tokenizer"] == "whitespace-v1"
    assert value["performance"]["latency_ms"]["status"] == "absent"
    assert value["performance"]["gpu_hours"]["value"] is None


def test_analysis_reports_recorded_performance_and_unclassified_failure_stage(
    tmp_path: Path,
) -> None:
    store, registry, _ = _fixture(tmp_path, performance=True)
    value = analyze(registry, store).to_dict()
    assert value["performance"]["latency_ms"]["value"]["mean"] == 4.0
    assert value["performance"]["gpu_hours"]["status"] == "absent"
    assert value["failures"]["value"]["stage_status"] == "absent"
    assert value["failures"]["value"]["events"][0]["stage"] is None


def test_dashboard_has_stable_sections_and_escaped_static_html(tmp_path: Path) -> None:
    store, registry, _ = _fixture(tmp_path)
    dashboard = project(store, registry)
    value = dashboard.to_dict()
    assert tuple(value["section_order"]) == SECTIONS
    assert set(value["sections"]) == set(SECTIONS)
    artifacts = value["sections"]["Artifacts"]
    model = next(row for row in artifacts if row["kind"] == "model")
    assert model["parameters"]["path"] == "[redacted]"
    rendered = render_html(dashboard)
    assert "&lt;script&gt;" in rendered
    assert "<script>" not in rendered
    assert "/private/weights.safetensors" not in dashboard.to_json()
