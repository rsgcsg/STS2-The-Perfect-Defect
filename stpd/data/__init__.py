"""Canonical STPD data, manifest, split, and integrity APIs."""

from .b0 import B0Finding, B0Report, validate_b0
from .human_annotator import (
    HumanImportReport,
    HumanRecordRejection,
    ImportedHumanRecord,
    RejectedHumanRecord,
    import_human_recording,
    import_verified_human_bundle,
)
from .human_corpus import (
    CollectionCampaign,
    CollectionProfile,
    CorpusBuildResult,
    HumanCorpusError,
    LocalDirectorySessionStore,
    SessionRegistryEntry,
    VerifiedSessionBundle,
    build_human_corpus,
    freeze_smoke_handoff,
    inspect_corpus_snapshot,
    register_session_bundle,
    verify_session_bundle,
)
from .lifecycle_profile import LifecycleProfileError, profile_canonical_dataset
from .manifest import DataFile, DataManifest, DataSource
from .parquet import read_transition_parquet, write_transition_parquet
from .pipeline import DatasetBuildError, build_canonical_dataset, read_raw_jsonl
from .records import research_action_from_record, research_state_from_record
from .splits import SplitAssignment, assign_episode_splits
from .training_handoff import (
    TrainingHandoffError,
    build_training_input,
    resolve_training_object,
    stage_training_input,
    verify_training_input,
)

__all__ = [
    "B0Finding",
    "B0Report",
    "DataFile",
    "DataManifest",
    "DataSource",
    "DatasetBuildError",
    "HumanImportReport",
    "HumanCorpusError",
    "HumanRecordRejection",
    "ImportedHumanRecord",
    "CollectionCampaign",
    "CollectionProfile",
    "CorpusBuildResult",
    "LocalDirectorySessionStore",
    "LifecycleProfileError",
    "RejectedHumanRecord",
    "SessionRegistryEntry",
    "SplitAssignment",
    "TrainingHandoffError",
    "VerifiedSessionBundle",
    "assign_episode_splits",
    "build_canonical_dataset",
    "build_human_corpus",
    "build_training_input",
    "freeze_smoke_handoff",
    "import_human_recording",
    "import_verified_human_bundle",
    "inspect_corpus_snapshot",
    "profile_canonical_dataset",
    "read_raw_jsonl",
    "read_transition_parquet",
    "research_action_from_record",
    "research_state_from_record",
    "register_session_bundle",
    "resolve_training_object",
    "stage_training_input",
    "validate_b0",
    "write_transition_parquet",
    "verify_training_input",
    "verify_session_bundle",
]
