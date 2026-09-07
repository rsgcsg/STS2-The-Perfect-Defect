"""Bounded, local-first analysis over published STPD artifacts.

This module intentionally treats DuckDB as a disposable query mechanism.  The
durable authority remains the manifest, its immutable payloads, and the
registry projection.  Missing operational measurements are represented as
``status=absent``; no timing, memory, throughput, or GPU values are inferred.
"""

from __future__ import annotations

import io
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ..artifact_contracts import Manifest
from ..storage.registry import Registry
from ..storage.store import ArtifactStore

SCHEMA = "stpd/local-analysis-v1"
_KNOWN_PERFORMANCE = (
    "latency_ms",
    "vram_mb",
    "throughput_samples_per_s",
    "gpu_hours",
)
_TOKEN_RE = re.compile(r"\S+")


def _present(value: Any, *, source: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "present", "value": value}
    if source is not None:
        result["source"] = source
    return result


def _absent(reason: str) -> dict[str, Any]:
    return {"status": "absent", "value": None, "reason": reason}


def _summary(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "p50": None, "p95": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
        "p50": ordered[(len(ordered) - 1) // 2],
        "p95": ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)],
    }


def _read_payload(store: ArtifactStore, manifest: Manifest, role: str) -> bytes:
    return b"".join(store.read_payload(manifest.payload(role)))


def _interfaces(
    first: Registry | ArtifactStore, second: ArtifactStore | Registry
) -> tuple[Registry, ArtifactStore]:
    """Accept both natural call orders while keeping the public ports narrow."""
    if hasattr(first, "manifests") and hasattr(second, "read_payload"):
        return cast(Registry, first), cast(ArtifactStore, second)
    if hasattr(second, "manifests") and hasattr(first, "read_payload"):
        return cast(Registry, second), cast(ArtifactStore, first)
    raise TypeError("analyze requires a Registry and an ArtifactStore")


def _load_parquet_rows(store: ArtifactStore, manifest: Manifest) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    raw = _read_payload(store, manifest, "metrics")
    return cast(list[dict[str, Any]], pq.read_table(io.BytesIO(raw)).to_pylist())


def _load_samples(store: ArtifactStore, manifest: Manifest) -> list[dict[str, Any]]:
    raw = _read_payload(store, manifest, "samples")
    samples: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                continue
            samples.append(value)
    return samples


def _metric_rows(
    rows: Sequence[Mapping[str, Any]], *, baseline: str, metric: str | None = None
) -> dict[str, Any]:
    selected = [row for row in rows if row.get("baseline") == baseline]
    if not selected:
        return {"status": "absent", "value": None, "reason": "no evaluation rows"}
    value: Any = (
        statistics.fmean(float(row[metric]) for row in selected)
        if metric is not None
        else {
            name: statistics.fmean(float(row[name]) for row in selected)
            for name in ("top1", "mrr", "nll", "margin")
        }
    )
    return _present(value, source=f"offline_evaluation:{baseline}")


def _calibration(rows: Sequence[Mapping[str, Any]], *, baseline: str) -> dict[str, Any]:
    selected = [row for row in rows if row.get("baseline") == baseline]
    if not selected:
        return _absent("no evaluation rows")
    bins: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in selected:
        confidence = max(0.0, min(0.999999, float(row["confidence"])))
        bins[int(confidence * 10)].append(row)
    ece = sum(
        len(values) / len(selected)
        * abs(
            statistics.fmean(float(row["confidence"]) for row in values)
            - statistics.fmean(float(row["top1"]) for row in values)
        )
        for values in bins.values()
    )
    return _present(
        {
            "ece_10_bins": ece,
            "bins": {
                str(index): {
                    "count": len(values),
                    "confidence": statistics.fmean(float(row["confidence"]) for row in values),
                    "top1": statistics.fmean(float(row["top1"]) for row in values),
                }
                for index, values in sorted(bins.items())
            },
        },
        source=f"offline_evaluation:{baseline}",
    )


def _dict_counts(values: Iterable[Any]) -> dict[str, int]:
    return {
        str(key): count
        for key, count in sorted(Counter(values).items(), key=lambda item: str(item[0]))
    }


def _nested_metric_values(
    value: Any, wanted: set[str], path: str = "parameters"
) -> dict[str, tuple[float, str]]:
    found: dict[str, tuple[float, str]] = {}
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text in wanted and type(child) in {int, float} and math.isfinite(float(child)):
                found.setdefault(key_text, (float(child), f"{path}.{key_text}"))
            found.update(_nested_metric_values(child, wanted, f"{path}.{key_text}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.update(_nested_metric_values(child, wanted, f"{path}[{index}]"))
    return found


def _duckdb_rows(rows: list[dict[str, Any]], database: str | Path | None) -> list[dict[str, Any]]:
    """Run the bounded grouping query through DuckDB and return plain rows."""
    if not rows:
        return []
    import duckdb
    import pyarrow as pa

    columns = sorted({key for row in rows for key in row})
    table = pa.Table.from_pylist([{key: row.get(key) for key in columns} for row in rows])
    connection = duckdb.connect(str(database) if database is not None else ":memory:")
    try:
        connection.register("evaluation_rows", table)
        result = connection.execute(
            """
            SELECT baseline, surface, family, split, candidate_count, count(*) AS row_count,
                   avg(top1) AS top1, avg(mrr) AS mrr, avg(nll) AS nll, avg(margin) AS margin
            FROM evaluation_rows
            GROUP BY baseline, surface, family, split, candidate_count
            ORDER BY baseline, surface, family, split, candidate_count
            """
        ).fetchall()
        return [
            {
                "baseline": row[0],
                "surface": row[1],
                "family": row[2],
                "split": row[3],
                "candidate_count": int(row[4]),
                "count": int(row[5]),
                "top1": float(row[6]),
                "mrr": float(row[7]),
                "nll": float(row[8]),
                "margin": float(row[9]),
            }
            for row in result
        ]
    finally:
        connection.close()


@dataclass(frozen=True)
class AnalysisReport:
    """Stable JSON-ready local analysis projection."""

    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json.loads(json.dumps(self.payload, sort_keys=True, separators=(",", ":"))),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def analyze(
    registry: Registry | ArtifactStore,
    store: ArtifactStore | Registry,
    *,
    artifact_ids: Iterable[str] | None = None,
    duckdb_path: str | Path | None = None,
) -> AnalysisReport:
    """Analyze published evaluation/model-view artifacts through local DuckDB.

    ``artifact_ids`` narrows the evaluation roots; omitted roots use every
    indexed offline evaluation.  The optional database path is a local cache
    for the query only and is never emitted in the report.
    """
    registry, store = _interfaces(registry, store)
    allowed = set(artifact_ids) if artifact_ids is not None else None
    evaluations = [
        manifest
        for manifest in registry.manifests("offline_evaluation")
        if allowed is None or manifest.artifact_id in allowed
    ]
    raw_rows: list[dict[str, Any]] = []
    view_ids: set[str] = set()
    for manifest in evaluations:
        info = manifest.parameters.value()
        baseline = str(info.get("baseline", "model"))
        view_ids.add(manifest.parent("model_view"))
        for row in _load_parquet_rows(store, manifest):
            row["baseline"] = baseline
            row["evaluation_id"] = manifest.artifact_id
            raw_rows.append(row)
    grouped = _duckdb_rows(raw_rows, duckdb_path)
    model_rows = [row for row in raw_rows if row["baseline"] == "model"]
    baselines = sorted({str(row["baseline"]) for row in raw_rows})

    metric_names = ("top1", "mrr", "nll", "margin")
    metrics = {
        name: _metric_rows(raw_rows, baseline="model", metric=name) for name in metric_names
    }
    metrics["calibration"] = _calibration(raw_rows, baseline="model")
    by_baseline = {
        baseline: {
            name: _metric_rows(raw_rows, baseline=baseline, metric=name)["value"]
            for name in metric_names
        }
        for baseline in baselines
    }
    metrics["by_baseline"] = (
        _present(by_baseline, source="DuckDB grouped evaluation rows")
        if by_baseline
        else _absent("no evaluation rows")
    )

    distributions: dict[str, Any]
    if raw_rows:
        distributions = {
            "decision": _present(
                {
                    "rows": len(raw_rows),
                    "groups": len(grouped),
                    "model_rows": len(model_rows),
                    "by_baseline": _dict_counts(row["baseline"] for row in raw_rows),
                    "by_split": _dict_counts(row["split"] for row in raw_rows),
                },
                source="DuckDB evaluation rows",
            ),
            "surface": _present(_dict_counts(row["surface"] for row in raw_rows), source="DuckDB"),
            "family": _present(_dict_counts(row["family"] for row in raw_rows), source="DuckDB"),
            "candidate_count": _present(
                _dict_counts(row["candidate_count"] for row in raw_rows), source="DuckDB"
            ),
        }
    else:
        distributions = {
            name: _absent("no indexed offline evaluation rows")
            for name in ("decision", "surface", "family", "candidate_count")
        }

    token_counts: list[int] = []
    state_token_counts: list[int] = []
    action_token_counts: list[int] = []
    for view_id in sorted(view_ids):
        view = registry.get(view_id)
        for sample in _load_samples(store, view):
            state_tokens = len(_TOKEN_RE.findall(str(sample.get("state_text", ""))))
            action_tokens = sum(
                len(_TOKEN_RE.findall(str(value))) for value in sample.get("action_texts", [])
            )
            state_token_counts.append(state_tokens)
            action_token_counts.append(action_tokens)
            token_counts.extend((state_tokens, action_tokens))
    distributions["tokens"] = (
        _present(
            {
                "tokenizer": "whitespace-v1",
                "state": _summary(state_token_counts),
                "actions_per_decision": _summary(action_token_counts),
                "state_and_actions": _summary(token_counts),
            },
            source="model_view serialized text",
        )
        if token_counts
        else _absent("no indexed model-view samples")
    )

    datasets = registry.manifests("dataset")
    data_amount = [
        {
            "artifact_id": manifest.artifact_id,
            "records": manifest.parameters.value().get("records"),
            "runs": manifest.parameters.value().get("runs"),
            "scope": manifest.parameters.value().get("scope"),
        }
        for manifest in datasets
    ]
    data_projection = (
        _present(data_amount, source="dataset manifests")
        if data_amount
        else _absent("no indexed datasets")
    )
    ablation = (
        _present(
            [
                {
                    "baseline": baseline,
                    "rows": sum(1 for row in raw_rows if row["baseline"] == baseline),
                    "metrics": by_baseline[baseline],
                }
                for baseline in baselines
            ],
            source="offline evaluation manifests",
        )
        if baselines
        else _absent("no indexed offline evaluations")
    )

    recorded: dict[str, list[dict[str, Any]]] = defaultdict(list)
    failures: list[dict[str, Any]] = []
    for kind in ("performance", "run_event", "run_result"):
        for manifest in registry.manifests(kind):
            values = _nested_metric_values(manifest.parameters.value(), set(_KNOWN_PERFORMANCE))
            for name, (value, source) in values.items():
                recorded[name].append(
                    {"value": value, "source": f"{manifest.artifact_id}:{source}"}
                )
            info = manifest.parameters.value()
            if kind == "run_event" and info.get("kind") in {"attempt_failed", "failed"}:
                details_value = info.get("details")
                details: Mapping[str, Any] = (
                    details_value if isinstance(details_value, Mapping) else {}
                )
                stage = details.get("stage", info.get("stage"))
                code = details.get("code", info.get("code"))
                failures.append(
                    {
                        "artifact_id": manifest.artifact_id,
                        "stage": stage if isinstance(stage, str) else None,
                        "stage_status": "present" if isinstance(stage, str) else "absent",
                        "code": code if isinstance(code, str) else None,
                    }
                )
    performance = {
        name: (
            _present(
                _summary([entry["value"] for entry in recorded[name]]),
                source="recorded performance manifests",
            )
            if recorded[name]
            else _absent("no recorded performance metric")
        )
        for name in _KNOWN_PERFORMANCE
    }
    stage_values = [event["stage"] for event in failures if event["stage_status"] == "present"]
    failure_projection: dict[str, Any]
    if failures:
        failure_projection = _present(
            {
                "events": failures,
                "by_stage": _dict_counts(stage_values) if stage_values else None,
                "stage_status": "present" if stage_values else "absent",
            },
            source="run_event manifests",
        )
    else:
        failure_projection = _absent("no recorded failure run events")

    payload = {
        "schema": SCHEMA,
        "artifact_ids": sorted(manifest.artifact_id for manifest in evaluations),
        "engine": {"name": "duckdb", "query": "evaluation-grouped-v1"},
        "metrics": metrics,
        "distributions": distributions,
        "ablation": ablation,
        "data_amount": data_projection,
        "performance": performance,
        "failures": failure_projection,
        "non_claims": [
            "Analysis is a local projection of published artifacts, not research admission "
            "or a scientific verdict.",
            "Token counts use whitespace-v1 and are not Qwen tokenizer measurements.",
            "Absent performance values were not inferred from elapsed wall time or payload size.",
        ],
    }
    return AnalysisReport(payload)
