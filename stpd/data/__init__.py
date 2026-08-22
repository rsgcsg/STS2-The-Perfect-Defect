"""Canonical STPD data, manifest, split, and integrity APIs."""

from .b0 import B0Finding, B0Report, validate_b0
from .manifest import DataFile, DataManifest, DataSource
from .parquet import read_transition_parquet, write_transition_parquet
from .pipeline import DatasetBuildError, build_canonical_dataset, read_raw_jsonl
from .splits import SplitAssignment, assign_episode_splits

__all__ = [
    "B0Finding",
    "B0Report",
    "DataFile",
    "DataManifest",
    "DataSource",
    "DatasetBuildError",
    "SplitAssignment",
    "assign_episode_splits",
    "build_canonical_dataset",
    "read_raw_jsonl",
    "read_transition_parquet",
    "validate_b0",
    "write_transition_parquet",
]
