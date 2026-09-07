"""Deterministic Gold-dev/Gold-test campaign planning and E0-E7 harness policy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ..canonical import semantic_hash
from ..json_boundary import BoundaryError, FrozenObject, digest, unsigned
from .data import AdmittedDataset
from .gold import GoldSplit, GoldTask, assert_gold_access, sample_gold_tasks
from .representation import FullRunSerializer

HARNESS_SCHEMA = "stpd/fullrun-engineering-harness-v1"
HARNESS_STAGES = ("E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7")
HARNESS_STAGE_DESCRIPTIONS = {
    "E0": "admission",
    "E1": "pretrained/random frozen controls",
    "E2": "Linear/MLP heads",
    "E3": "baselines and leakage checks",
    "E4": "shared Full-Run representation and candidate path",
    "E5": "Lite/Standard/Full serializer profiles",
    "E6": "deferred dynamics",
    "E7": "sealed offline and live evaluation deferred",
}


@dataclass(frozen=True)
class GoldCampaign:
    """A label-free campaign plan with disjoint whole-run Gold partitions."""

    gold_dev: tuple[GoldTask, ...]
    gold_test: tuple[GoldTask, ...]
    seed: int
    serializer: FrozenObject
    source_dataset_id: str

    def validate(self) -> None:
        unsigned(self.seed, "campaign.seed")
        if not isinstance(self.serializer, FrozenObject):
            raise BoundaryError("campaign", "invalid_serializer_identity")
        if len(self.gold_dev) == 0 or len(self.gold_test) == 0:
            raise BoundaryError("campaign", "both_gold_partitions_required")
        digest(self.source_dataset_id, "campaign.source_dataset_id")
        for task in (*self.gold_dev, *self.gold_test):
            task.validate()
        if any(task.gold_split != "gold_dev" for task in self.gold_dev):
            raise BoundaryError("campaign", "gold_dev_task_split_mismatch")
        if any(task.gold_split != "gold_test" for task in self.gold_test):
            raise BoundaryError("campaign", "gold_test_task_split_mismatch")
        dev_ids = {task.task_id for task in self.gold_dev}
        test_ids = {task.task_id for task in self.gold_test}
        if dev_ids & test_ids:
            raise BoundaryError("campaign", "gold_task_overlap")
        dev_runs = {task.run_id for task in self.gold_dev}
        test_runs = {task.run_id for task in self.gold_test}
        if dev_runs & test_runs:
            raise BoundaryError("campaign", "gold_run_overlap")
        if any(
            task.source_dataset_id != self.source_dataset_id
            for task in (*self.gold_dev, *self.gold_test)
        ):
            raise BoundaryError("campaign", "gold_source_dataset_mismatch")

    @property
    def campaign_id(self) -> str:
        self.validate()
        return semantic_hash(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        self.validate()
        result: dict[str, Any] = {
            "schema": "stpd/fullrun-gold-campaign-v1",
            "seed": self.seed,
            "serializer": self.serializer.value(),
            "source_dataset_id": self.source_dataset_id,
            "gold_dev": [task.to_dict() for task in self.gold_dev],
            "gold_test": [task.to_dict() for task in self.gold_test],
        }
        if include_id:
            result["campaign_id"] = semantic_hash(result)
        return result

    @classmethod
    def from_dataset(
        cls,
        dataset: AdmittedDataset,
        *,
        dev_count: int,
        test_count: int,
        seed: int = 0,
        surface_quotas_dev: Mapping[str, int] | None = None,
        surface_quotas_test: Mapping[str, int] | None = None,
        source_split: str | None = None,
        serializer: FullRunSerializer | None = None,
    ) -> GoldCampaign:
        unsigned(seed, "campaign.seed")
        if (
            type(dev_count) is not int
            or dev_count <= 0
            or type(test_count) is not int
            or test_count <= 0
        ):
            raise BoundaryError("campaign", "invalid_partition_count")
        serializer = serializer or FullRunSerializer()
        if source_split is not None:
            raise BoundaryError("campaign", "gold_uses_existing_dev_and_test")
        dev = sample_gold_tasks(
            dataset,
            gold_split="gold_dev",
            count=dev_count,
            surface_quotas=surface_quotas_dev,
            seed=seed,
            serializer=serializer,
        )
        test = sample_gold_tasks(
            dataset,
            gold_split="gold_test",
            count=test_count,
            surface_quotas=surface_quotas_test,
            seed=seed,
            serializer=serializer,
        )
        campaign = cls(dev, test, seed, FrozenObject.of(serializer.identity), dataset.logical_id)
        campaign.validate()
        return campaign


@dataclass(frozen=True)
class FullRunHarnessConfig:
    """The bounded engineering matrix; it does not authorize scientific claims."""

    schema: str = HARNESS_SCHEMA
    stages: tuple[str, ...] = HARNESS_STAGES
    admission_contract: str = "ResearchTransitionV1"
    require_complete_catalog: bool = True
    require_causal_successor_or_terminal: bool = True
    backbone_controls: tuple[str, ...] = ("pretrained", "random")
    frozen_backbone: bool = True
    heads: tuple[str, ...] = ("linear", "mlp")
    baselines: tuple[str, ...] = ("uniform_legal", "action_only")
    leakage_checks: bool = True
    candidate_permutation: bool = True
    label_permutation: bool = True
    shared_fullrun_model_view: bool = True
    serializer_profiles: tuple[str, ...] = ("lite", "standard", "full")
    dynamics: str = "deferred"
    sealed_offline: str = "deferred"
    live_evaluation: str = "deferred"
    gold_test_access: bool = False
    scientific_claims: bool = False

    def validate(self) -> None:
        if self.schema != HARNESS_SCHEMA:
            raise BoundaryError("harness", "unsupported_schema")
        if self.stages != HARNESS_STAGES:
            raise BoundaryError("harness", "incomplete_or_reordered_stages")
        if self.admission_contract != "ResearchTransitionV1":
            raise BoundaryError("harness", "wrong_admission_contract")
        if not self.require_complete_catalog or not self.require_causal_successor_or_terminal:
            raise BoundaryError("harness", "admission_gate_weakened")
        if self.backbone_controls != ("pretrained", "random") or not self.frozen_backbone:
            raise BoundaryError("harness", "frozen_pretrained_random_controls_required")
        if self.heads != ("linear", "mlp"):
            raise BoundaryError("harness", "unsupported_head_matrix")
        if self.baselines != ("uniform_legal", "action_only") or not self.leakage_checks:
            raise BoundaryError("harness", "baseline_or_leakage_controls_missing")
        if not self.candidate_permutation or not self.label_permutation:
            raise BoundaryError("harness", "permutation_controls_missing")
        if not self.shared_fullrun_model_view:
            raise BoundaryError("harness", "shared_fullrun_path_required")
        if self.serializer_profiles != ("lite", "standard", "full"):
            raise BoundaryError("harness", "serializer_matrix_mismatch")
        if self.dynamics != "deferred":
            raise BoundaryError("harness", "dynamics_not_deferred")
        if self.sealed_offline != "deferred" or self.live_evaluation != "deferred":
            raise BoundaryError("harness", "sealed_or_live_stage_enabled")
        if self.gold_test_access or self.scientific_claims:
            raise BoundaryError("harness", "engineering_config_cannot_claim_science")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "stages": list(self.stages),
            "stage_descriptions": dict(HARNESS_STAGE_DESCRIPTIONS),
            "admission": {
                "contract": self.admission_contract,
                "complete_catalog": self.require_complete_catalog,
                "successor_or_terminal": self.require_causal_successor_or_terminal,
            },
            "E1": {
                "backbone_controls": list(self.backbone_controls),
                "frozen": self.frozen_backbone,
            },
            "E2": {"heads": list(self.heads)},
            "E3": {
                "baselines": list(self.baselines),
                "leakage_checks": self.leakage_checks,
                "candidate_permutation": self.candidate_permutation,
                "label_permutation": self.label_permutation,
            },
            "E4": {"shared_fullrun_model_view": self.shared_fullrun_model_view},
            "E5": {"serializer_profiles": list(self.serializer_profiles)},
            "E6": {"dynamics": self.dynamics},
            "E7": {
                "sealed_offline": self.sealed_offline,
                "live_evaluation": self.live_evaluation,
                "gold_test_access": self.gold_test_access,
            },
            "scientific_claims": self.scientific_claims,
        }

    @property
    def engineering_only(self) -> bool:
        return not self.scientific_claims

    @property
    def dynamics_deferred(self) -> bool:
        return self.dynamics == "deferred"

    @property
    def sealed_offline_deferred(self) -> bool:
        return self.sealed_offline == "deferred"

    @property
    def live_deferred(self) -> bool:
        return self.live_evaluation == "deferred"


def default_harness_config() -> FullRunHarnessConfig:
    config = FullRunHarnessConfig()
    config.validate()
    return config


def validate_harness_config(config: FullRunHarnessConfig) -> FullRunHarnessConfig:
    config.validate()
    return config


def assert_campaign_access(
    mode: Literal["training", "tuning", "evaluation"], split: GoldSplit
) -> None:
    assert_gold_access(split, mode=mode)


E0_ADMISSION = "E0"
E1_FROZEN_CONTROLS = "E1"
E2_HEADS = "E2"
E3_BASELINES_LEAKAGE = "E3"
E4_SHARED_FULLRUN = "E4"
E5_SERIALIZER_PROFILES = "E5"
E6_DEFERRED_DYNAMICS = "E6"
E7_SEALED_OFFLINE_LIVE_DEFERRED = "E7"
