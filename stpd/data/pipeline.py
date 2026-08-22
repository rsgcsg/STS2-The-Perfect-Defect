"""Fail-closed raw JSONL to canonical Parquet dataset pipeline."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..canonical import canonical_json, semantic_hash
from ..contracts import ContractError
from .b0 import B0Report, validate_b0
from .manifest import DataFile, DataManifest, DataSource
from .parquet import write_transition_parquet
from .splits import SplitAssignment, assign_episode_splits


class DatasetBuildError(ContractError):
    """Raised when raw input cannot pass the canonical dataset gate."""


def read_raw_jsonl(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Read immutable raw records without correcting or defaulting missing fields."""

    records: list[dict[str, Any]] = []
    for path_value in paths:
        path = Path(path_value)
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    message = f"{path}:{line_number}: invalid JSON: {error}"
                    raise DatasetBuildError(message) from error
                if not isinstance(value, dict):
                    raise DatasetBuildError(f"{path}:{line_number}: transition must be an object")
                records.append(value)
    if not records:
        raise DatasetBuildError("raw dataset contains no records")
    return records


def build_canonical_dataset(
    records: Iterable[dict[str, Any]],
    *,
    output_dir: str | Path,
    schema_root: str | Path,
    source: DataSource | None = None,
    sources: Sequence[DataSource] | None = None,
    stpd_source_revision: str,
    created_at: str,
    split_salt: str,
    split_assignments: Mapping[str, SplitAssignment] | None = None,
    split_strategy: str = "seed_root_sha256_v0",
    deduplication: Mapping[str, Any] | None = None,
) -> tuple[DataManifest, B0Report]:
    """Gate, split, write, and manifest one canonical dataset atomically by directory."""

    materialized = list(records)
    if source is not None and sources is not None:
        raise DatasetBuildError("provide source or sources, not both")
    resolved_sources = tuple(sources or (() if source is None else (source,)))
    if not resolved_sources:
        raise DatasetBuildError("canonical dataset requires at least one source")
    for item in resolved_sources:
        item.validate()
    assignments = dict(
        split_assignments
        if split_assignments is not None
        else assign_episode_splits(materialized, salt=split_salt)
    )
    episodes = {str(record.get("episode_id", "")) for record in materialized}
    if not episodes or set(assignments) != episodes:
        raise DatasetBuildError("split assignments must cover exactly all dataset episodes")
    report = validate_b0(materialized, schema_root=schema_root, splits=assignments)
    if report.verdict != "pass":
        codes = sorted({finding.code for finding in report.findings})
        raise DatasetBuildError(f"B0 failed: {','.join(codes)}")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    parquet_path = destination / "transitions.parquet"
    row_count, dataset_hash = write_transition_parquet(materialized, parquet_path)
    data_file = DataFile.from_path(
        parquet_path,
        rows=row_count,
        semantic_hash_=dataset_hash,
    )
    split_counts = Counter(assignment.split for assignment in assignments.values())
    serialized_split_assignments = {
        episode: assignment.split for episode, assignment in sorted(assignments.items())
    }
    manifest = DataManifest(
        manifest_id=f"dataset-{dataset_hash[:16]}",
        created_at=created_at,
        source_revision=stpd_source_revision,
        contract_schema="stpd/research-transition-v0",
        sources=resolved_sources,
        files=(data_file,),
        row_count=row_count,
        split={
            "strategy": split_strategy,
            "salt_hash": semantic_hash(split_salt),
            "episode_counts": dict(sorted(split_counts.items())),
            "assignments": serialized_split_assignments,
            "assignments_hash": semantic_hash(serialized_split_assignments),
        },
        deduplication=dict(deduplication or {
            "exact_record_duplicates": 0,
            "cross_split_semantic_duplicates": 0,
            "decision_fingerprint": "state+legal_actions+chosen_action-v0",
        }),
        eligibility_counts=report.eligibility_counts,
        truncation_applied=False,
        non_claims=(
            "B0 dataset integrity does not prove label quality or model quality.",
            "Fixture or imported data does not prove current Headless runtime semantics.",
        ),
    )
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(canonical_json(manifest.to_dict()) + "\n", encoding="utf-8")
    return manifest, report
