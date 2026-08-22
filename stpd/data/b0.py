"""Executable B0 dataset-integrity and leakage gate."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from ..canonical import CanonicalizationError, reject_model_input_leakage, semantic_hash
from .manifest import DataManifest
from .splits import SplitAssignment

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class B0Finding:
    code: str
    severity: Severity
    transition_id: str | None
    detail: str


@dataclass(frozen=True)
class B0Report:
    verdict: Literal["pass", "fail"]
    record_count: int
    findings: tuple[B0Finding, ...]
    eligibility_counts: dict[str, int]
    environment_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "stpd/b0-report-v0",
            "verdict": self.verdict,
            "record_count": self.record_count,
            "findings": [finding.__dict__ for finding in self.findings],
            "eligibility_counts": self.eligibility_counts,
            "environment_count": self.environment_count,
        }


def _validator(schema_root: Path) -> Draft202012Validator:
    documents: dict[str, dict[str, Any]] = {}
    for name in ("research-state-v0", "research-action-v0", "research-transition-v0"):
        value = json.loads((schema_root / f"{name}.schema.json").read_text())
        documents[value["$id"]] = value
    registry = Registry().with_resources(
        (uri, Resource.from_contents(value)) for uri, value in documents.items()
    )
    transition = next(value for uri, value in documents.items() if "transition" in uri)
    return Draft202012Validator(transition, registry=registry)


def validate_b0(
    records: Iterable[Mapping[str, Any]],
    *,
    schema_root: str | Path,
    manifest: DataManifest | None = None,
    splits: Mapping[str, SplitAssignment] | None = None,
) -> B0Report:
    """Validate frozen contracts, fair-player inputs, successor links, and split isolation."""

    materialized = list(records)
    findings: list[B0Finding] = []
    validator = _validator(Path(schema_root))
    transition_ids: set[str] = set()
    exact_hashes: dict[str, str] = {}
    semantic_splits: defaultdict[str, set[str]] = defaultdict(set)
    environments: set[str] = set()
    eligibility = Counter[str]()

    for record in materialized:
        transition_id = str(record.get("transition_id", "")) or None
        errors = sorted(validator.iter_errors(record), key=lambda error: list(error.path))
        for error in errors:
            findings.append(B0Finding("schema_invalid", "error", transition_id, error.message))
        if errors:
            continue
        assert transition_id is not None
        if transition_id in transition_ids:
            findings.append(
                B0Finding("duplicate_transition_id", "error", transition_id, "duplicate id")
            )
        transition_ids.add(transition_id)
        record_hash = semantic_hash(record)
        if record_hash in exact_hashes:
            findings.append(
                B0Finding(
                    "duplicate_record",
                    "error",
                    transition_id,
                    f"duplicates {exact_hashes[record_hash]}",
                )
            )
        exact_hashes[record_hash] = transition_id
        try:
            reject_model_input_leakage(record["state"])
            for action in record["legal_actions"]:
                reject_model_input_leakage(action)
        except CanonicalizationError as error:
            findings.append(B0Finding("model_input_leakage", "error", transition_id, str(error)))
        action_keys = [action["action_key"] for action in record["legal_actions"]]
        if len(action_keys) != len(set(action_keys)):
            findings.append(B0Finding("duplicate_action_key", "error", transition_id, "not unique"))
        chosen_key = record["chosen_action"]["action_key"]
        if action_keys.count(chosen_key) != 1:
            findings.append(
                B0Finding("ambiguous_chosen_action", "error", transition_id, chosen_key)
            )
        current_eligibility = record["eligibility"]
        if current_eligibility["rank"]:
            eligibility["rank"] += 1
        if current_eligibility["transition"]:
            eligibility["transition"] += 1
        if current_eligibility["return"]:
            eligibility["return"] += 1
        if (
            current_eligibility["rank_mode"] == "full_listwise"
            and current_eligibility["legal_action_completeness"] != "complete"
        ):
            findings.append(
                B0Finding("incomplete_listwise_catalog", "error", transition_id, "not complete")
            )
        if not record["terminal"] and not record["scope_exit"] and record["successor"] is None:
            findings.append(B0Finding("missing_successor", "error", transition_id, "required"))
        forbidden_reasons = {"unknown_delivery", "identity_drift", "settling_timeout"}
        present = forbidden_reasons.intersection(current_eligibility["reason_codes"])
        if present:
            findings.append(
                B0Finding(
                    "inadmissible_lifecycle", "error", transition_id, ",".join(sorted(present))
                )
            )
        environment_hash = semantic_hash(record["environment"])
        environments.add(environment_hash)
        decision_hash = semantic_hash(
            {
                "state": record["state"],
                "legal_actions": record["legal_actions"],
                "chosen_action": record["chosen_action"],
            }
        )
        if splits is not None:
            assignment = splits.get(record["episode_id"])
            if assignment is None:
                findings.append(
                    B0Finding("missing_split", "error", transition_id, "episode missing")
                )
            else:
                semantic_splits[decision_hash].add(assignment.split)

    for decision_hash, names in semantic_splits.items():
        if len(names) > 1:
            findings.append(
                B0Finding(
                    "cross_split_semantic_duplicate",
                    "error",
                    None,
                    f"{decision_hash}:{','.join(sorted(names))}",
                )
            )
    if manifest is not None:
        try:
            manifest.validate()
            if manifest.row_count != len(materialized):
                findings.append(
                    B0Finding("manifest_row_count", "error", None, "does not match records")
                )
        except Exception as error:
            findings.append(B0Finding("manifest_invalid", "error", None, str(error)))
    return B0Report(
        "fail" if any(item.severity == "error" for item in findings) else "pass",
        len(materialized),
        tuple(findings),
        dict(eligibility),
        len(environments),
    )
