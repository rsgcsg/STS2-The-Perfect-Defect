"""Candidate-aligned offline metrics and whole-run uncertainty; no model-quality verdict."""

from __future__ import annotations

import io
import math
import random
import statistics
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from typing import Any

from ..artifact_contracts import Manifest, Parent, Producer
from ..json_boundary import BoundaryError, FrozenObject, json_bytes, unsigned
from ..storage.store import ArtifactStore
from .features import ModelSample, load_model_view

EVALUATION_SCHEMA = "stpd/offline-ranking-evaluation-v1"


def candidate_metrics(scores: Sequence[float], acceptable: Sequence[int]) -> dict[str, float]:
    values = tuple(float(value) for value in scores)
    labels = tuple(acceptable)
    if (
        not values
        or any(not math.isfinite(value) for value in values)
        or not labels
        or len(set(labels)) != len(labels)
        or any(type(index) is not int or not 0 <= index < len(values) for index in labels)
    ):
        raise BoundaryError("evaluation", "invalid_scores_or_acceptable_actions")
    top = max(values)
    winners = [index for index, value in enumerate(values) if value == top]
    top1 = len(set(winners) & set(labels)) / len(winners)
    reciprocal = 0.0
    for score in sorted(set(values), reverse=True):
        block = [index for index, value in enumerate(values) if value == score]
        good = len(set(block) & set(labels))
        if not good:
            continue
        above = sum(value > score for value in values)
        total = len(block)
        survival = 1.0
        for offset in range(total - good + 1):
            first_probability = survival * good / (total - offset)
            reciprocal += first_probability / (above + offset + 1)
            survival *= (total - offset - good) / (total - offset)
        break
    exponentials = [math.exp(value - top) for value in values]
    denominator = sum(exponentials)
    accepted_max = max(values[index] for index in labels)
    accepted_logsum = accepted_max + math.log(
        sum(math.exp(values[i] - accepted_max) for i in labels)
    )
    nll = top + math.log(denominator) - accepted_logsum
    ordered = sorted(values, reverse=True)
    return {
        "top1": top1,
        "mrr": reciprocal,
        "nll": max(0.0, nll),
        "confidence": 1.0 / denominator,
        "margin": ordered[0] - ordered[1] if len(ordered) > 1 else 0.0,
    }


def action_only_prior(
    samples: tuple[ModelSample, ...],
) -> Callable[[ModelSample], tuple[float, ...]]:
    counts: Counter[str] = Counter()
    for sample in samples:
        if sample.split == "train":
            counts[sample.action_texts[sample.chosen_index]] += 1
    if not counts:
        raise BoundaryError("evaluation", "action_prior_requires_training_data")
    return lambda sample: tuple(math.log(counts[action] + 1) for action in sample.action_texts)


def summarize_rows(
    rows: list[dict[str, Any]], *, seed: int, bootstrap: int = 200
) -> dict[str, Any]:
    unsigned(seed, "evaluation.seed")
    unsigned(bootstrap, "evaluation.bootstrap")
    if not rows:
        raise BoundaryError("evaluation", "empty_evaluation")

    def mean(selected: list[dict[str, Any]]) -> dict[str, float | int]:
        return {
            "count": len(selected),
            **{
                metric: statistics.fmean(row[metric] for row in selected)
                for metric in ("top1", "mrr", "nll", "confidence", "margin")
            },
        }

    result: dict[str, Any] = {"overall": mean(rows)}
    for dimension in ("surface", "family", "candidate_count", "run_id"):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row[dimension])].append(row)
        result["by_" + dimension] = {key: mean(value) for key, value in sorted(grouped.items())}
    bins: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        bins[min(9, int(row["confidence"] * 10))].append(row)
    result["ece_10_bins"] = sum(
        len(values)
        / len(rows)
        * abs(
            statistics.fmean(row["confidence"] for row in values)
            - statistics.fmean(row["top1"] for row in values)
        )
        for values in bins.values()
    )
    by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_run[row["run_id"]].append(row)
    if len(by_run) < 2 or bootstrap < 20:
        result["bootstrap"] = {
            "status": "insufficient_independent_runs_or_replicates",
            "unit": "whole_run",
            "runs": len(by_run),
        }
    else:
        rng = random.Random(seed)
        run_ids = sorted(by_run)
        draws: dict[str, list[float]] = defaultdict(list)
        for _ in range(bootstrap):
            selected = [row for _ in run_ids for row in by_run[rng.choice(run_ids)]]
            for metric in ("top1", "mrr", "nll"):
                draws[metric].append(statistics.fmean(row[metric] for row in selected))
        result["bootstrap"] = {
            "status": "computed",
            "unit": "whole_run",
            "runs": len(run_ids),
            "seed": seed,
            "replicates": bootstrap,
            "percentile_95": {
                metric: [
                    sorted(values)[int(bootstrap * 0.025)],
                    sorted(values)[min(bootstrap - 1, int(bootstrap * 0.975))],
                ]
                for metric, values in draws.items()
            },
        }
    return result


def evaluate_samples(
    samples: tuple[ModelSample, ...],
    scorer: Callable[[int], Sequence[float]],
    *,
    partition: str = "dev",
    seed: int = 0,
    bootstrap: int = 200,
    permit_test: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if partition not in {"dev", "test"} or (partition == "test" and not permit_test):
        raise BoundaryError("evaluation", "sealed_test_requires_explicit_protocol_admission")
    rows = []
    for index, sample in enumerate(samples):
        if sample.split != partition:
            continue
        scores = tuple(scorer(index))
        if len(scores) != len(sample.action_texts):
            raise BoundaryError("evaluation", "candidate_alignment_mismatch")
        metrics = candidate_metrics(scores, (sample.chosen_index,))
        rows.append(
            {
                "transition_id": sample.transition_id,
                "run_id": sample.run_id,
                "surface": sample.surface,
                "family": sample.family,
                "split": sample.split,
                "candidate_count": len(scores),
                **metrics,
            }
        )
    return rows, summarize_rows(rows, seed=seed, bootstrap=bootstrap)


def publish_evaluation(
    store: ArtifactStore,
    model: Manifest,
    view_id: str,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    producer: Producer,
    *,
    partition: str,
    baseline: str = "model",
) -> Manifest:
    import pyarrow as pa
    import pyarrow.parquet as pq

    if model.kind != "model" or model.parameters.value().get("schema") != "stpd/scheme1-model-v1":
        raise BoundaryError("evaluation", "model_contract_mismatch")
    if model.producer != producer:
        raise BoundaryError("evaluation", "model_producer_mismatch")
    if partition not in {"dev", "test"}:
        raise BoundaryError("evaluation", "invalid_evaluation_partition")
    view, expected_samples = load_model_view(store, view_id)
    model_parameters = model.parameters.value()
    view_parameters = view.parameters.value()
    training_input = store.get_manifest(model.parent("training_input"))
    if (
        model.parent("model_view") != view_id
        or training_input.kind != "training_input"
        or training_input.parent("model_view") != view_id
        or training_input.parameters.value().get("qwen") != model_parameters.get("qwen")
        or model_parameters.get("scope") != view_parameters.get("scope")
        or model_parameters.get("serializer") != view_parameters.get("serializer")
    ):
        raise BoundaryError("evaluation", "model_view_identity_mismatch")
    expected = {
        sample.transition_id: sample
        for sample in expected_samples
        if sample.split == partition
    }
    transition_ids = [row.get("transition_id") for row in rows]
    if any(not isinstance(value, str) for value in transition_ids) or len(
        set(transition_ids)
    ) != len(rows):
        raise BoundaryError("evaluation", "row_inventory_mismatch")
    required = {
        "transition_id",
        "run_id",
        "surface",
        "family",
        "split",
        "candidate_count",
        "top1",
        "mrr",
        "nll",
        "confidence",
        "margin",
    }
    for row in rows:
        if set(row) != required:
            raise BoundaryError("evaluation", "row_schema_mismatch")
        sample = expected.get(row["transition_id"])
        if sample is None or any(
            row[field] != getattr(sample, field)
            for field in ("run_id", "surface", "family", "split")
        ):
            raise BoundaryError("evaluation", "row_input_mismatch")
        if row["candidate_count"] != len(sample.action_texts):
            raise BoundaryError("evaluation", "candidate_alignment_mismatch")
        if type(row["candidate_count"]) is not int or row["candidate_count"] < 1:
            raise BoundaryError("evaluation", "invalid_candidate_count")
        metrics = tuple(row[name] for name in ("top1", "mrr", "nll", "confidence", "margin"))
        if any(type(value) not in {int, float} or not math.isfinite(value) for value in metrics):
            raise BoundaryError("evaluation", "invalid_metric")
        if not 0 <= row["top1"] <= 1 or not 0 <= row["mrr"] <= 1 or not 0 <= row["confidence"] <= 1:
            raise BoundaryError("evaluation", "metric_out_of_range")

    with tempfile.TemporaryFile("w+b") as handle:
        pq.write_table(pa.Table.from_pylist(rows), handle, compression="zstd", version="2.6")
        handle.seek(0)
        row_payload = store.put_payload("metrics", handle, "application/vnd.apache.parquet")
    summary_payload = store.put_payload(
        "summary", io.BytesIO(json_bytes(summary)), "application/json"
    )
    manifest = Manifest(
        "offline_evaluation",
        producer,
        (Parent("model", model.artifact_id), Parent("model_view", view_id)),
        (row_payload, summary_payload),
        FrozenObject.of(
            {
                "schema": EVALUATION_SCHEMA,
                "partition": partition,
                "baseline": baseline,
                "tie_policy": "uniform_within_equal_score_blocks",
                "rows": len(rows),
                "scope": model.parameters.value()["scope"],
                "scientific_verdict": "not_claimed",
            }
        ),
    )
    store.publish(manifest)
    return manifest
