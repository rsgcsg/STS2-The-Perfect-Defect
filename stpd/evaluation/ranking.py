"""B1 candidate-set metrics without action flattening."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..models import RankBatch

ScoreFunction = Callable[[str, tuple[str, ...]], list[float]]


@dataclass(frozen=True)
class RankingMetrics:
    count: int
    top1_accuracy: float
    mean_reciprocal_rank: float
    mean_listwise_nll: float
    pairwise_accuracy: float
    by_source: dict[str, dict[str, float]]


def _evaluate_group(scores: list[float], target: int) -> tuple[float, float, float, float]:
    if not scores or not 0 <= target < len(scores):
        raise ValueError("score vector and target are invalid")
    order = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
    rank = order.index(target) + 1
    max_score = max(scores)
    log_sum_exp = max_score + math.log(sum(math.exp(score - max_score) for score in scores))
    comparisons = [scores[target] > score for index, score in enumerate(scores) if index != target]
    pairwise = sum(comparisons) / len(comparisons) if comparisons else 1.0
    return float(rank == 1), 1.0 / rank, -scores[target] + log_sum_exp, pairwise


def evaluate_ranking(batches: Iterable[RankBatch], scorer: ScoreFunction) -> RankingMetrics:
    rows: list[tuple[str, tuple[float, float, float, float]]] = []
    for batch in batches:
        batch.validate()
        scores = scorer(batch.state_text, batch.action_texts)
        if len(scores) != len(batch.action_texts):
            raise ValueError("scorer did not preserve candidate count")
        rows.append((batch.source_id, _evaluate_group(scores, batch.target_index)))
    if not rows:
        raise ValueError("ranking evaluation requires at least one batch")

    def summarize(values: list[tuple[float, float, float, float]]) -> dict[str, float]:
        return {
            "top1_accuracy": sum(row[0] for row in values) / len(values),
            "mean_reciprocal_rank": sum(row[1] for row in values) / len(values),
            "mean_listwise_nll": sum(row[2] for row in values) / len(values),
            "pairwise_accuracy": sum(row[3] for row in values) / len(values),
        }

    grouped: defaultdict[str, list[tuple[float, float, float, float]]] = defaultdict(list)
    for source, values in rows:
        grouped[source].append(values)
    overall = summarize([values for _, values in rows])
    return RankingMetrics(
        len(rows),
        overall["top1_accuracy"],
        overall["mean_reciprocal_rank"],
        overall["mean_listwise_nll"],
        overall["pairwise_accuracy"],
        {source: summarize(values) for source, values in sorted(grouped.items())},
    )
