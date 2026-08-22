from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from stpd.data import SplitAssignment
from stpd.experiments import ExperimentPreparationError, build_rank_batches, select_tiny_records

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "research-transition-v0.golden.json"
CONFIG = ROOT / "configs" / "v0" / "experiments" / "l2-tiny-overfit.json"


def _records() -> list[dict]:
    first = json.loads(FIXTURE.read_text(encoding="utf-8"))
    second = copy.deepcopy(first)
    second["transition_id"] = "transition-000002"
    second["step_index"] = 1
    second["raw_ref"] = "raw/fixture/episode-fixture.jsonl.zst#1"
    return [first, second]


def test_tiny_subset_is_hash_sorted_train_only_and_candidate_aligned() -> None:
    records = list(reversed(_records()))
    assignments = {
        "episode-fixture": SplitAssignment("episode-fixture", "STPDFIXTURE00001", "train")
    }
    config = json.loads(CONFIG.read_text(encoding="utf-8"))

    selected = select_tiny_records(records, assignments, config)
    batches = build_rank_batches(selected)

    assert len(selected) == 2
    assert {batch.target_index for batch in batches} == {0}
    assert all(len(batch.action_texts) == 2 for batch in batches)
    assert all("action_key" not in text for batch in batches for text in batch.action_texts)


def test_tiny_subset_fails_closed_without_two_rank_eligible_train_rows() -> None:
    records = _records()
    records[1]["eligibility"]["rank"] = False
    records[1]["eligibility"]["rank_mode"] = "none"
    assignments = {
        "episode-fixture": SplitAssignment("episode-fixture", "STPDFIXTURE00001", "train")
    }
    config = json.loads(CONFIG.read_text(encoding="utf-8"))

    with pytest.raises(ExperimentPreparationError, match="too few"):
        select_tiny_records(records, assignments, config)


def test_tiny_retry_config_changes_only_bounded_budget_identity() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))

    assert config["protocol_version"] == "stpd-v0-l2-2026-08-22-r1"
    assert config["architecture_id"] == "scheme1-linear-pretrained"
    assert config["input_profile"] == "stpd-combat-v0-standard"
    assert config["qwen_control"] == "pretrained"
    assert config["seed"] == 20260822
    assert config["optimizer"] == {
        "name": "adamw",
        "learning_rate": 0.001,
        "weight_decay": 0.0,
        "grad_clip_norm": 1.0,
    }
    assert config["budget"] == {
        "optimizer_steps": 256,
        "evaluation_interval_steps": 1,
        "checkpoint_steps": [0, 256],
    }
    assert config["pass_criteria"] == {
        "memorized_top1_fraction": 1.0,
        "maximum_final_mean_listwise_nll": 0.1,
        "minimum_relative_mean_loss_reduction": 0.9,
        "qwen_gradient_tensor_count": 0,
        "all_values_finite": True,
    }
    assert config["boundaries"] == {
        "gold_dev_allowed": False,
        "gold_test_allowed": False,
        "b6_allowed": False,
        "scientific_claim_allowed": False,
        "owner_execution_required": True,
    }


def test_core_matrix_is_exactly_ten_configs_three_seeds_and_no_fake_qwen() -> None:
    matrix = json.loads((ROOT / "configs" / "v0" / "models" / "core.json").read_text())
    architectures = matrix["architectures"]
    assert matrix["plan_version"] == "stpd-v0-l2-2026-08-22-r1"
    assert len(architectures) == 10
    assert len(matrix["training_seeds"]) == 3
    assert matrix["expected_core_run_count"] == 30
    assert {value["qwen_control"] for value in architectures.values()} == {
        "pretrained",
        "random",
    }
    assert all(value["qwen_control"] != "fake" for value in architectures.values())
