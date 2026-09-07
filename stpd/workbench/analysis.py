"""Verified artifact projections computed with disposable local DuckDB."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..fullrun.data import load_dataset
from ..fullrun.evaluation import load_evaluation
from ..fullrun.features import load_model_view
from ..json_boundary import BoundaryError
from ..storage.registry import Registry
from ..storage.store import ArtifactStore

SCHEMA = "stpd/local-analysis-v1"
PERFORMANCE = ("latency_ms", "vram_mb", "throughput_samples_per_s", "gpu_hours")


def present(value: Any) -> dict[str, Any]:
    return {"status": "present", "value": value}


def absent(reason: str) -> dict[str, Any]:
    return {"status": "absent", "value": None, "reason": reason}


@dataclass(frozen=True)
class AnalysisReport:
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.to_json())  # type: ignore[no-any-return]

    def to_json(self) -> str:
        return json.dumps(self.payload, sort_keys=True, ensure_ascii=False, allow_nan=False)


def analyze(
    registry: Registry,
    store: ArtifactStore,
    *,
    artifact_ids: Iterable[str] | None = None,
    duckdb_path: str | Path | None = None,
) -> AnalysisReport:
    import duckdb
    import pyarrow as pa

    allowed = set(artifact_ids) if artifact_ids is not None else None
    evaluations = [
        m
        for m in registry.manifests("offline_evaluation")
        if allowed is None or m.artifact_id in allowed
    ]
    if allowed is not None and allowed != {m.artifact_id for m in evaluations}:
        raise BoundaryError("analysis", "evaluation_not_indexed")
    # Sealed-test metrics never enter a tuning dashboard through a default discovery scan.
    sealed = [m.artifact_id for m in evaluations if m.parameters.value().get("partition") == "test"]
    evaluations = [m for m in evaluations if m.artifact_id not in sealed]
    rows: list[dict[str, Any]] = []
    comparisons = []
    for manifest in evaluations:
        loaded = load_evaluation(store, manifest.artifact_id)
        info = manifest.parameters.value()
        training = store.get_manifest(loaded.model.parent("training_input"))
        dataset, _ = load_dataset(store, loaded.view.parent("dataset"))
        config = training.parameters.value()["config"]
        comparisons.append(
            {
                "evaluation_id": manifest.artifact_id,
                "model_id": loaded.model.artifact_id,
                "training_input_id": training.artifact_id,
                "dataset_id": dataset.artifact_id,
                "records": dataset.parameters.value()["records"],
                "runs": dataset.parameters.value()["runs"],
                "head": config["head"],
                "config": config,
                "serializer": loaded.view.parameters.value()["serializer"],
                "qwen": training.parameters.value()["qwen"],
                "baseline": info["baseline"],
                "metrics": loaded.summary["overall"],
            }
        )
        rows.extend(
            {**row, "evaluation_id": manifest.artifact_id, "baseline": info["baseline"]}
            for row in loaded.rows
        )
    decisions: list[dict[str, Any]] = []
    datasets = []
    for manifest in registry.manifests("dataset"):
        verified, data = load_dataset(store, manifest.artifact_id)
        datasets.append(
            {
                "artifact_id": verified.artifact_id,
                "records": len(data.records),
                "runs": len(data.splits.value()),
                "scope": data.scope,
            }
        )
        decisions.extend(
            {
                "dataset_id": manifest.artifact_id,
                "transition_id": r.transition_id,
                "surface": r.surface,
                "family": r.family,
                "candidate_count": len(r.actions),
            }
            for r in data.records
        )
    tokens: list[dict[str, Any]] = []
    for manifest in registry.manifests("model_view"):
        _, samples = load_model_view(store, manifest.artifact_id)
        for sample in samples:
            # Explicit engineering proxy, never called exact Qwen token profiling.
            tokens.extend(
                {
                    "state": len(sample.state_text.split()),
                    "action": len(action.split()),
                    "joint": len(sample.state_text.split()) + len(action.split()),
                }
                for action in sample.action_texts
            )
    performance_rows = []
    failures = []
    for manifest in registry.manifests():
        info = manifest.parameters.value()
        if manifest.kind == "performance":
            for name in PERFORMANCE:
                value = info.get(name)
                if value is not None:
                    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
                        raise BoundaryError("analysis", "invalid_performance_measurement")
                    performance_rows.append({"metric": name, "value": float(value)})
        if manifest.kind == "run_event" and info.get("kind") == "attempt_failed":
            details = info.get("details", {})
            failures.append(
                {
                    "artifact_id": manifest.artifact_id,
                    "stage": details.get("stage"),
                    "code": details.get("code"),
                }
            )
    connection = duckdb.connect(str(duckdb_path) if duckdb_path else ":memory:")

    def query(sql: str) -> list[dict[str, Any]]:
        result = connection.execute(sql)
        columns = [item[0] for item in result.description]
        return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]

    def register(name: str, values: list[dict[str, Any]]) -> None:
        connection.register(name, pa.Table.from_pylist(values))

    try:
        metrics: dict[str, Any] = {
            name: absent("no model evaluation")
            for name in ("top1", "mrr", "nll", "margin", "calibration")
        }
        grouped = []
        if rows:
            register("evaluations", rows)
            grouped = query(
                "SELECT evaluation_id, baseline, surface, family, candidate_count, "
                "count(*) AS count, avg(top1) AS top1, avg(mrr) AS mrr, "
                "avg(nll) AS nll, avg(margin) AS margin FROM evaluations "
                "GROUP BY ALL ORDER BY evaluation_id, surface, family, candidate_count"
            )
            overall = query(
                "SELECT avg(top1) AS top1, avg(mrr) AS mrr, avg(nll) AS nll, "
                "avg(margin) AS margin FROM evaluations WHERE baseline='model'"
            )[0]
            metrics.update(
                {
                    name: present(value) if value is not None else absent("no model rows")
                    for name, value in overall.items()
                }
            )
            calibration = query(
                "SELECT evaluation_id, least(9, floor(confidence*10)) AS bin, "
                "count(*) AS count, avg(confidence) AS confidence, avg(top1) AS top1 "
                "FROM evaluations WHERE baseline='model' GROUP BY ALL "
                "ORDER BY evaluation_id, bin"
            )
            metrics["calibration"] = (
                present(calibration) if calibration else absent("no model rows")
            )
        distributions: dict[str, Any] = {}
        if decisions:
            register("decisions", decisions)
            distributions["decision"] = present(
                query(
                    "SELECT dataset_id, count(*) AS records FROM decisions "
                    "GROUP BY ALL ORDER BY dataset_id"
                )
            )
            for dimension in ("surface", "family", "candidate_count"):
                distributions[dimension] = present(
                    query(
                        f"SELECT dataset_id, {dimension}, count(*) AS count FROM decisions "
                        f"GROUP BY ALL ORDER BY dataset_id, {dimension}"
                    )
                )
        else:
            distributions.update(
                {
                    name: absent("no datasets")
                    for name in ("decision", "surface", "family", "candidate_count")
                }
            )
        if tokens:
            register("tokens", tokens)
            distributions["tokens"] = present(
                {
                    "tokenizer": "whitespace-v1",
                    "joint": query(
                        "SELECT count(*) AS count, min(joint) AS min, max(joint) AS max, "
                        "avg(joint) AS mean, quantile_disc(joint, 0.95) AS p95 FROM tokens"
                    )[0],
                }
            )
        else:
            distributions["tokens"] = absent("no model views")
        performance = {name: absent("no recorded measurement") for name in PERFORMANCE}
        if performance_rows:
            register("performance", performance_rows)
            for row in query(
                "SELECT metric, count(*) AS count, avg(value) AS mean, "
                "min(value) AS min, max(value) AS max FROM performance GROUP BY ALL"
            ):
                performance[row.pop("metric")] = present(row)
        failure_report = absent("no failure events")
        if failures:
            register("failures", failures)
            failure_report = present(
                {
                    "events": failures,
                    "by_stage": query(
                        "SELECT stage, count(*) AS count FROM failures "
                        "GROUP BY stage ORDER BY stage"
                    ),
                    "stage_status": "present" if all(f["stage"] for f in failures) else "absent",
                }
            )
        return AnalysisReport(
            {
                "schema": SCHEMA,
                "engine": {"name": "duckdb", "query": "verified-lineage-v1"},
                "artifact_ids": [m.artifact_id for m in evaluations],
                "sealed_evaluations_omitted": sealed,
                "metrics": metrics,
                "groups": grouped,
                "distributions": distributions,
                "ablation": present(comparisons) if comparisons else absent("no evaluations"),
                "data_amount": present(datasets) if datasets else absent("no datasets"),
                "performance": performance,
                "failures": failure_report,
                "non_claims": [
                    "scientific significance of pooled metrics",
                    "whitespace counts are not Qwen tokenizer counts",
                    "missing performance metrics are not inferred",
                ],
            }
        )
    finally:
        connection.close()
