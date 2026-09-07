"""Bounded Full-Run Gold task, annotation, and audit contracts.

This module owns the research-side Gold boundary.  It can select immutable tasks from an
admitted :class:`~stpd.fullrun.data.AdmittedDataset`, but it never turns the observed
``chosen_key`` into a Gold label.  A label is accepted only when its origin is explicit.
Synthetic labels are available solely through an explicit engineering override used by
tests and fixtures.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ..canonical import semantic_hash
from ..json_boundary import BoundaryError, FrozenObject, digest, text, unsigned
from .contracts import ResearchTransitionV1
from .data import AdmittedDataset
from .representation import FullRunSerializer

GOLD_SCHEMA = "stpd/fullrun-gold-v1"
GOLD_TASK_SCHEMA = "stpd/fullrun-gold-task-v1"
GOLD_ANNOTATION_SCHEMA = "stpd/fullrun-gold-annotation-v1"
GoldSplit = Literal["gold_dev", "gold_test"]
GoldDisposition = Literal["accepted", "invalid", "insufficient_information"]
GoldOrigin = Literal["human", "synthetic_fixture"]


def _finite_confidence(value: float | None) -> None:
    if value is not None and (type(value) not in {int, float} or not math.isfinite(value)):
        raise BoundaryError("gold.annotation", "invalid_confidence")
    if value is not None and not 0 <= value <= 1:
        raise BoundaryError("gold.annotation", "invalid_confidence")


@dataclass(frozen=True)
class GoldTask:
    """A label-free, candidate-complete task presented to a Gold annotator."""

    task_id: str
    transition_id: str
    run_id: str
    surface: str
    family: str
    state_text: str
    action_keys: tuple[str, ...]
    action_texts: tuple[str, ...]
    candidate_display_order: tuple[str, ...]
    gold_split: GoldSplit
    source_scope: str
    serializer: FrozenObject
    source_dataset_id: str | None = None

    def validate(self) -> None:
        digest(self.task_id, "gold.task_id")
        digest(self.transition_id, "gold.transition_id")
        text(self.run_id, "gold.run_id")
        text(self.surface, "gold.surface")
        text(self.family, "gold.family")
        if (
            not isinstance(self.state_text, str)
            or not self.state_text
            or len(self.state_text) > 4 * 1024 * 1024
        ):
            raise BoundaryError("gold.task", "invalid_state_text")
        if self.gold_split not in {"gold_dev", "gold_test"}:
            raise BoundaryError("gold.task", "unknown_gold_split")
        if self.source_scope not in {"engineering", "platform_qualified"}:
            raise BoundaryError("gold.task", "unknown_source_scope")
        if not isinstance(self.serializer, FrozenObject):
            raise BoundaryError("gold.task", "invalid_serializer_identity")
        if not self.action_keys or len(self.action_keys) != len(set(self.action_keys)):
            raise BoundaryError("gold.task", "empty_or_duplicate_candidate_catalog")
        if len(self.action_keys) != len(self.action_texts):
            raise BoundaryError("gold.task", "candidate_text_alignment_mismatch")
        if any(not isinstance(value, str) or not value for value in self.action_texts):
            raise BoundaryError("gold.task", "invalid_action_text")
        if set(self.candidate_display_order) != set(self.action_keys):
            raise BoundaryError("gold.task", "display_order_not_catalog_permutation")
        if self.source_dataset_id is not None:
            digest(self.source_dataset_id, "gold.source_dataset_id")

    @property
    def state_hash(self) -> str:
        """Stable state identity exposed for agreement grouping."""

        return semantic_hash({"schema": GOLD_TASK_SCHEMA, "transition": self.transition_id})

    @classmethod
    def from_transition(
        cls,
        transition: ResearchTransitionV1,
        serializer: FullRunSerializer,
        *,
        gold_split: GoldSplit,
        display_seed: int,
        source_dataset_id: str | None = None,
    ) -> GoldTask:
        if not transition.rank_eligible:
            raise BoundaryError("gold.task", "transition_not_rank_eligible")
        unsigned(display_seed, "gold.display_seed")
        state_text, action_texts = serializer.serialize(transition)
        action_keys = tuple(action.key for action in transition.actions)
        order = list(action_keys)
        random.Random(f"stpd-gold-display-v1:{display_seed}:{transition.transition_id}").shuffle(
            order
        )
        task_id = semantic_hash(
            {
                "schema": GOLD_TASK_SCHEMA,
                "transition_id": transition.transition_id,
                "gold_split": gold_split,
                "display_seed": display_seed,
                "serializer": serializer.identity,
            }
        )
        task = cls(
            task_id,
            transition.transition_id,
            transition.run_id,
            transition.surface,
            transition.family,
            state_text,
            action_keys,
            action_texts,
            tuple(order),
            gold_split,
            transition.provenance.scope,
            FrozenObject.of(serializer.identity),
            source_dataset_id,
        )
        task.validate()
        return task

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": GOLD_TASK_SCHEMA,
            "task_id": self.task_id,
            "transition_id": self.transition_id,
            "run_id": self.run_id,
            "surface": self.surface,
            "family": self.family,
            "state_text": self.state_text,
            "action_keys": list(self.action_keys),
            "action_texts": list(self.action_texts),
            "candidate_display_order": list(self.candidate_display_order),
            "gold_split": self.gold_split,
            "source_scope": self.source_scope,
            "serializer": self.serializer.value(),
            "source_dataset_id": self.source_dataset_id,
        }


@dataclass(frozen=True)
class GoldAnnotation:
    """One explicit annotation for a GoldTask.

    ``synthetic_fixture`` is intentionally rejected by default.  Callers that need a
    deterministic test label must pass ``allow_synthetic=True`` to ``validate`` or to
    the audit/build function; production code has no implicit fixture-label path.
    """

    annotation_id: str
    task_id: str
    annotator_id: str
    gold_split: GoldSplit
    candidate_action_keys: tuple[str, ...]
    candidate_display_order: tuple[str, ...]
    disposition: GoldDisposition
    acceptable_actions: tuple[str, ...] = ()
    best_action: str | None = None
    confidence: float | None = None
    origin: GoldOrigin = "human"
    annotation_version: str = GOLD_ANNOTATION_SCHEMA
    state_hash: str | None = None

    def validate(self, *, allow_synthetic: bool = False) -> None:
        text(self.annotation_id, "gold.annotation_id")
        digest(self.task_id, "gold.annotation.task_id")
        text(self.annotator_id, "gold.annotator_id")
        if self.gold_split not in {"gold_dev", "gold_test"}:
            raise BoundaryError("gold.annotation", "unknown_gold_split")
        if self.disposition not in {"accepted", "invalid", "insufficient_information"}:
            raise BoundaryError("gold.annotation", "unknown_disposition")
        if self.origin not in {"human", "synthetic_fixture"}:
            raise BoundaryError("gold.annotation", "unknown_origin")
        if self.origin == "synthetic_fixture" and not allow_synthetic:
            raise BoundaryError("gold.annotation", "synthetic_gold_requires_explicit_override")
        text(self.annotation_version, "gold.annotation_version")
        if (
            not self.candidate_action_keys
            or len(self.candidate_action_keys) != len(set(self.candidate_action_keys))
            or set(self.candidate_display_order) != set(self.candidate_action_keys)
        ):
            raise BoundaryError("gold.annotation", "invalid_candidate_catalog")
        acceptable = set(self.acceptable_actions)
        if len(acceptable) != len(self.acceptable_actions):
            raise BoundaryError("gold.annotation", "duplicate_acceptable_action")
        if self.disposition == "accepted":
            if not acceptable or not acceptable.issubset(self.candidate_action_keys):
                raise BoundaryError("gold.annotation", "acceptable_actions_outside_catalog")
            if self.best_action is not None and self.best_action not in acceptable:
                raise BoundaryError("gold.annotation", "best_action_outside_acceptable_set")
            if self.confidence is None:
                raise BoundaryError("gold.annotation", "accepted_annotation_requires_confidence")
            _finite_confidence(self.confidence)
        else:
            if acceptable or self.best_action is not None:
                raise BoundaryError("gold.annotation", "nonaccepted_disposition_has_label")
            if self.confidence is not None:
                _finite_confidence(self.confidence)
        if self.state_hash is not None:
            digest(self.state_hash, "gold.annotation.state_hash")

    @property
    def accepted(self) -> bool:
        return self.disposition == "accepted"

    def to_dict(self) -> dict[str, Any]:
        # Serialization is a production boundary.  Synthetic labels are only accepted by
        # an explicit audit/test call and are never silently materialized as Gold data.
        self.validate()
        return {
            "schema": self.annotation_version,
            "annotation_id": self.annotation_id,
            "task_id": self.task_id,
            "annotator_id": self.annotator_id,
            "gold_split": self.gold_split,
            "candidate_action_keys": list(self.candidate_action_keys),
            "candidate_display_order": list(self.candidate_display_order),
            "disposition": self.disposition,
            "acceptable_actions": list(self.acceptable_actions),
            "best_action": self.best_action,
            "confidence": self.confidence,
            "origin": self.origin,
            "state_hash": self.state_hash,
        }


@dataclass(frozen=True)
class GoldAuditReport:
    gold_split: GoldSplit
    sealed: bool
    task_count: int
    annotation_count: int
    covered_task_count: int
    coverage: float
    disposition_counts: dict[str, int]
    surface_counts: dict[str, dict[str, int]]
    double_labeled_tasks: int
    best_action_agreement: float | None
    acceptable_overlap: float | None
    agreement_pairs: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": GOLD_SCHEMA,
            "gold_split": self.gold_split,
            "sealed": self.sealed,
            "task_count": self.task_count,
            "annotation_count": self.annotation_count,
            "covered_task_count": self.covered_task_count,
            "coverage": self.coverage,
            "disposition_counts": dict(self.disposition_counts),
            "surface_counts": {
                surface: dict(values) for surface, values in sorted(self.surface_counts.items())
            },
            "double_labeled_tasks": self.double_labeled_tasks,
            "best_action_agreement": self.best_action_agreement,
            "acceptable_overlap": self.acceptable_overlap,
            "agreement_pairs": self.agreement_pairs,
        }


def _ordered_records(
    dataset: AdmittedDataset, source_split: str | None
) -> list[ResearchTransitionV1]:
    split_map = dataset.splits.value()
    records = [
        record
        for record in dataset.records
        if source_split is None or split_map.get(record.run_id) == source_split
    ]
    if not records:
        raise BoundaryError("gold.sampling", "no_records_for_source_split")
    if any(not record.rank_eligible for record in records):
        raise BoundaryError("gold.sampling", "dataset_contains_ineligible_record")
    return sorted(records, key=lambda record: record.transition_id)


def sample_gold_tasks(
    dataset: AdmittedDataset,
    *,
    gold_split: GoldSplit = "gold_dev",
    count: int | None = None,
    surface_quotas: Mapping[str, int] | None = None,
    source_split: str | None = None,
    seed: int = 0,
    serializer: FullRunSerializer | None = None,
    source_dataset_id: str | None = None,
) -> tuple[GoldTask, ...]:
    """Select deterministic, surface-aware, label-free Gold tasks.

    Quotas are exact minimum requests per surface.  A request larger than the available
    admitted population fails closed instead of silently substituting another surface.
    Without quotas, selection round-robins sorted surfaces so a large surface cannot consume
    the whole campaign.  The resulting tasks are never labels or a training dataset.
    """

    unsigned(seed, "gold.sampling.seed")
    if gold_split not in {"gold_dev", "gold_test"}:
        raise BoundaryError("gold.sampling", "unknown_gold_split")
    if count is not None and (type(count) is not int or count <= 0):
        raise BoundaryError("gold.sampling", "invalid_sample_count")
    serializer = serializer or FullRunSerializer()
    records = _ordered_records(dataset, source_split)
    by_surface: dict[str, list[ResearchTransitionV1]] = defaultdict(list)
    for record in records:
        by_surface[record.surface].append(record)
    for rows in by_surface.values():
        rows.sort(key=lambda record: semantic_hash([seed, record.transition_id]))
    quotas = dict(surface_quotas or {})
    for surface, requested in quotas.items():
        if type(requested) is not int or requested <= 0:
            raise BoundaryError("gold.sampling", "invalid_surface_quota")
        if surface not in by_surface or requested > len(by_surface[surface]):
            raise BoundaryError("gold.sampling", "insufficient_surface_coverage")
    selected: list[ResearchTransitionV1] = []
    if quotas:
        for surface in sorted(quotas):
            selected.extend(by_surface[surface][: quotas[surface]])
        if count is not None and len(selected) > count:
            raise BoundaryError("gold.sampling", "count_smaller_than_surface_quotas")
    target = count if count is not None else (sum(quotas.values()) if quotas else len(records))
    if target > len(records):
        raise BoundaryError("gold.sampling", "insufficient_admitted_tasks")
    selected_ids = {record.transition_id for record in selected}
    if len(selected) < target:
        surfaces = sorted(by_surface)
        cursor = 0
        while len(selected) < target:
            progressed = False
            for offset in range(len(surfaces)):
                surface = surfaces[(cursor + offset) % len(surfaces)]
                candidate = next(
                    (
                        record
                        for record in by_surface[surface]
                        if record.transition_id not in selected_ids
                    ),
                    None,
                )
                if candidate is not None:
                    selected.append(candidate)
                    selected_ids.add(candidate.transition_id)
                    progressed = True
                    if len(selected) == target:
                        break
            cursor += 1
            if not progressed:
                raise BoundaryError("gold.sampling", "insufficient_admitted_tasks")
    selected.sort(key=lambda record: semantic_hash([seed, record.transition_id]))
    source_dataset_id = source_dataset_id or dataset.logical_id
    digest(source_dataset_id, "gold.source_dataset_id")
    return tuple(
        GoldTask.from_transition(
            record,
            serializer,
            gold_split=gold_split,
            display_seed=seed,
            source_dataset_id=source_dataset_id,
        )
        for record in selected
    )


def audit_gold(
    tasks: Sequence[GoldTask],
    annotations: Sequence[GoldAnnotation],
    *,
    sealed: bool = False,
    allow_synthetic: bool = False,
) -> GoldAuditReport:
    """Validate labels and report coverage/agreement without imputing missing labels."""

    if not tasks:
        raise BoundaryError("gold.audit", "empty_task_set")
    for task in tasks:
        task.validate()
    splits = {task.gold_split for task in tasks}
    if len(splits) != 1:
        raise BoundaryError("gold.audit", "mixed_gold_splits")
    split = next(iter(splits))
    if split == "gold_test" and not sealed:
        raise BoundaryError("gold.audit", "gold_test_requires_seal")
    by_id = {task.task_id: task for task in tasks}
    if len(by_id) != len(tasks):
        raise BoundaryError("gold.audit", "duplicate_task_id")
    seen_annotations: set[str] = set()
    by_task: dict[str, list[GoldAnnotation]] = defaultdict(list)
    for annotation in annotations:
        annotation.validate(allow_synthetic=allow_synthetic)
        if annotation.annotation_id in seen_annotations:
            raise BoundaryError("gold.audit", "duplicate_annotation_id")
        seen_annotations.add(annotation.annotation_id)
        matched_task = by_id.get(annotation.task_id)
        if matched_task is None:
            raise BoundaryError("gold.audit", "annotation_task_not_found")
        if annotation.gold_split != matched_task.gold_split:
            raise BoundaryError("gold.audit", "annotation_split_mismatch")
        if set(annotation.candidate_action_keys) != set(matched_task.action_keys):
            raise BoundaryError("gold.audit", "annotation_catalog_mismatch")
        if set(annotation.candidate_display_order) != set(matched_task.action_keys):
            raise BoundaryError("gold.audit", "annotation_display_order_mismatch")
        by_task[annotation.task_id].append(annotation)
    accepted_tasks = {
        task_id for task_id, values in by_task.items() if any(value.accepted for value in values)
    }
    surface_counts: dict[str, dict[str, int]] = {}
    for task in tasks:
        values = by_task.get(task.task_id, ())
        counts = surface_counts.setdefault(
            task.surface,
            {
                "tasks": 0,
                "annotations": 0,
                "accepted": 0,
                "invalid": 0,
                "insufficient_information": 0,
            },
        )
        counts["tasks"] += 1
        counts["annotations"] += len(values)
        counts["accepted"] += sum(value.accepted for value in values)
        counts["invalid"] += sum(value.disposition == "invalid" for value in values)
        counts["insufficient_information"] += sum(
            value.disposition == "insufficient_information" for value in values
        )
    pairs = [values[:2] for values in by_task.values() if len(values) >= 2]
    best_pairs = [pair for pair in pairs if pair[0].accepted and pair[1].accepted]
    best_comparable = [
        pair
        for pair in best_pairs
        if pair[0].best_action is not None and pair[1].best_action is not None
    ]
    best_agreement = (
        sum(pair[0].best_action == pair[1].best_action for pair in best_comparable)
        / len(best_comparable)
        if best_comparable
        else None
    )
    overlap = (
        sum(
            len(set(pair[0].acceptable_actions) & set(pair[1].acceptable_actions))
            / len(set(pair[0].acceptable_actions) | set(pair[1].acceptable_actions))
            for pair in best_pairs
        )
        / len(best_pairs)
        if best_pairs
        else None
    )
    disposition_counts = Counter(annotation.disposition for annotation in annotations)
    return GoldAuditReport(
        split,
        sealed,
        len(tasks),
        len(annotations),
        len(accepted_tasks),
        len(accepted_tasks) / len(tasks),
        dict(sorted(disposition_counts.items())),
        dict(sorted(surface_counts.items())),
        len(pairs),
        best_agreement,
        overlap,
        len(best_pairs),
    )


def assert_gold_access(
    gold_split: GoldSplit, *, mode: Literal["training", "tuning", "evaluation"]
) -> None:
    """Enforce Gold isolation for training, tuning, and sealed evaluation."""

    if gold_split not in {"gold_dev", "gold_test"}:
        raise BoundaryError("gold.access", "unknown_gold_split")
    if mode == "training":
        raise BoundaryError("gold.access", "gold_isolation_training_forbidden")
    if mode == "tuning" and gold_split == "gold_test":
        raise BoundaryError("gold.access", "sealed_gold_test_tuning_forbidden")
    if mode == "evaluation" and gold_split == "gold_test":
        return
    if mode not in {"training", "tuning", "evaluation"}:
        raise BoundaryError("gold.access", "unknown_access_mode")


def assert_training_isolated(partitions: Iterable[str]) -> None:
    if any(partition in {"gold_dev", "gold_test"} for partition in partitions):
        raise BoundaryError("gold.access", "gold_isolation_training_forbidden")


# Names used by the bounded campaign runner and by callers that prefer explicit wording.
sample_surface_aware_tasks = sample_gold_tasks
FullRunGoldTask = GoldTask
FullRunGoldAnnotation = GoldAnnotation
