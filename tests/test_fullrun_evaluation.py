from __future__ import annotations

import itertools
import math

import pytest

from stpd.fullrun.evaluation import candidate_metrics, evaluate_samples, summarize_rows
from stpd.fullrun.features import ModelSample
from stpd.json_boundary import BoundaryError


def test_tie_metrics_are_permutation_neutral_and_probability_correct() -> None:
    scores = [1.0, 1.0, 1.0, 0.0]
    reference = candidate_metrics(scores, (0, 1))
    assert reference["top1"] == pytest.approx(2 / 3)
    assert reference["mrr"] == pytest.approx(5 / 6)
    for order in itertools.permutations(range(4)):
        actual = candidate_metrics([scores[i] for i in order], [order.index(0), order.index(1)])
        assert actual == pytest.approx(reference)
    uniform = candidate_metrics([0.0] * 4, [2])
    assert uniform["top1"] == 0.25
    assert uniform["mrr"] == pytest.approx(sum(1 / n for n in range(1, 5)) / 4)
    assert uniform["nll"] == pytest.approx(math.log(4))


def test_extreme_scores_do_not_underflow_and_bad_labels_fail() -> None:
    assert candidate_metrics([1000.0, -1000.0], [1])["nll"] == pytest.approx(2000.0)
    for scores, labels in [
        ([], [0]),
        ([math.nan], [0]),
        ([1.0], [1]),
        ([1.0], [True]),
        ([1.0, 2.0], [0, 0]),
    ]:
        with pytest.raises(BoundaryError):
            candidate_metrics(scores, labels)


def test_offline_evaluation_never_defaults_to_sealed_test() -> None:
    sample = ModelSample("t", "r", "test", "shop", "choice", "state", ("a", "b"), ("a", "b"), 0)
    with pytest.raises(BoundaryError, match="sealed_test"):
        evaluate_samples((sample,), lambda _: [0.0, 1.0], partition="test")
    dev = ModelSample("d", "r", "dev", "shop", "choice", "state", ("a", "b"), ("a", "b"), 0)
    rows, summary = evaluate_samples((dev, sample), lambda _: [0.0, 1.0])
    assert len(rows) == 1 and rows[0]["transition_id"] == "d"
    assert summary["bootstrap"]["status"] == "insufficient_independent_runs_or_replicates"


def test_bootstrap_resamples_whole_runs_and_is_deterministic() -> None:
    rows = [
        {
            "run_id": f"run-{i}",
            "surface": "event",
            "family": "choice",
            "candidate_count": 2,
            **candidate_metrics([float(i), 0.0], [0]),
        }
        for i in range(3)
    ]
    first = summarize_rows(rows, seed=19, bootstrap=50)
    assert first == summarize_rows(rows, seed=19, bootstrap=50)
    assert first["bootstrap"]["unit"] == "whole_run"
    assert first["bootstrap"]["runs"] == 3
    assert 0.0 <= first["ece_10_bins"] <= 1.0


def test_metrics_preserve_probability_under_large_logit_translation() -> None:
    import math

    import pytest

    from stpd.json_boundary import BoundaryError

    assert candidate_metrics((1e308, 1e308), (0,))["nll"] == pytest.approx(math.log(2))
    assert candidate_metrics((-1e308, -1e308), (0,))["nll"] == pytest.approx(math.log(2))
    with pytest.raises(BoundaryError, match="metric_overflow"):
        candidate_metrics((1e308, -1e308), (1,))
