from __future__ import annotations

from dataclasses import replace

import pytest

from stpd.fullrun.campaign import FullRunHarnessConfig, GoldCampaign, default_harness_config
from stpd.fullrun.data import admit
from stpd.fullrun.fixtures import SyntheticSourceAdapter, synthetic_bundle
from stpd.fullrun.gold import (
    GoldAnnotation,
    assert_gold_access,
    audit_gold,
    sample_gold_tasks,
)
from stpd.json_boundary import BoundaryError


def dataset():
    projection = SyntheticSourceAdapter().project(synthetic_bundle(runs=12, seed=4))
    return admit((projection,))


def test_sampling_is_label_free_surface_aware_and_reproducible() -> None:
    first = sample_gold_tasks(
        dataset(),
        count=12,
        surface_quotas={"combat": 2, "reward": 2},
        seed=9,
    )
    second = sample_gold_tasks(
        dataset(),
        count=12,
        surface_quotas={"combat": 2, "reward": 2},
        seed=9,
    )
    assert [task.to_dict() for task in first] == [task.to_dict() for task in second]
    assert sum(task.surface == "combat" for task in first) >= 2
    assert sum(task.surface == "reward" for task in first) >= 2
    assert all("chosen_key" not in task.state_text for task in first)
    assert all(task.gold_split == "gold_dev" for task in first)


def test_sampler_fails_closed_for_insufficient_surface_coverage() -> None:
    with pytest.raises(BoundaryError, match="insufficient_surface_coverage"):
        sample_gold_tasks(dataset(), surface_quotas={"combat": 13})


def test_campaign_keeps_gold_dev_and_test_on_disjoint_runs() -> None:
    campaign = GoldCampaign.from_dataset(dataset(), dev_count=6, test_count=6, seed=17)
    campaign.validate()
    assert {task.run_id for task in campaign.gold_dev}.isdisjoint(
        {task.run_id for task in campaign.gold_test}
    )
    assert campaign.campaign_id == campaign.to_dict()["campaign_id"]


def test_annotations_allow_multiple_acceptable_candidates_and_nonlabels() -> None:
    task = sample_gold_tasks(dataset(), count=1, seed=3)[0]
    accepted = GoldAnnotation(
        "a-accepted",
        task.task_id,
        "human-a",
        "gold_dev",
        task.action_keys,
        tuple(reversed(task.candidate_display_order)),
        "accepted",
        task.action_keys,
        None,
        0.8,
    )
    second = replace(
        accepted,
        annotation_id="a-second",
        annotator_id="human-b",
        best_action=task.action_keys[0],
    )
    insufficient = replace(
        accepted,
        annotation_id="a-insufficient",
        annotator_id="human-c",
        disposition="insufficient_information",
        acceptable_actions=(),
        best_action=None,
        confidence=None,
    )
    report = audit_gold([task], [accepted, second, insufficient])
    assert report.coverage == 1.0
    assert report.disposition_counts == {"accepted": 2, "insufficient_information": 1}
    assert report.acceptable_overlap == 1.0
    assert report.best_action_agreement is None


def test_synthetic_labels_require_an_explicit_engineering_override() -> None:
    task = sample_gold_tasks(dataset(), count=1, seed=3)[0]
    label = GoldAnnotation(
        "synthetic",
        task.task_id,
        "fixture",
        "gold_dev",
        task.action_keys,
        task.candidate_display_order,
        "accepted",
        (task.action_keys[0],),
        task.action_keys[0],
        1.0,
        "synthetic_fixture",
    )
    with pytest.raises(BoundaryError, match="synthetic_gold_requires_explicit_override"):
        audit_gold([task], [label])
    assert audit_gold([task], [label], allow_synthetic=True).coverage == 1.0


def test_gold_test_requires_seal_and_gold_isolation_is_enforced() -> None:
    task = sample_gold_tasks(dataset(), gold_split="gold_test", count=1, seed=8)[0]
    with pytest.raises(BoundaryError, match="gold_test_requires_seal"):
        audit_gold([task], [])
    with pytest.raises(BoundaryError, match="training_forbidden"):
        assert_gold_access("gold_dev", mode="training")
    with pytest.raises(BoundaryError, match="tuning_forbidden"):
        assert_gold_access("gold_test", mode="tuning")
    assert_gold_access("gold_test", mode="evaluation")


def test_harness_is_exact_engineering_matrix_and_rejects_promotion() -> None:
    config = default_harness_config()
    config.validate()
    assert config.to_dict()["stages"] == ["E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7"]
    assert config.engineering_only and config.dynamics_deferred and config.live_deferred
    with pytest.raises(BoundaryError, match="dynamics_not_deferred"):
        replace(config, dynamics="enabled").validate()
    with pytest.raises(BoundaryError, match="sealed_or_live_stage_enabled"):
        replace(config, live_evaluation="enabled").validate()
    with pytest.raises(BoundaryError, match="engineering_config_cannot_claim_science"):
        replace(config, scientific_claims=True).validate()
    with pytest.raises(BoundaryError, match="frozen_pretrained_random_controls_required"):
        replace(config, frozen_backbone=False).validate()
    assert isinstance(config, FullRunHarnessConfig)
