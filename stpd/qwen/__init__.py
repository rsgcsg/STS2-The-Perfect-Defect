"""Optional Qwen metadata and tokenizer tooling for the STPD L1 gate."""

from typing import Any

from .l1 import (
    DEFAULT_PIN_PATH,
    MODEL_ID,
    QwenL1Artifact,
    QwenL1Error,
    QwenL1Pin,
    QwenL1WeightError,
    discover_repo_revision,
    fetch_metadata_tokenizer,
    inspect_cache,
    load_pin,
    profile_jsonl,
    profile_records,
)
from .l2 import (
    DEFAULT_L2_PIN_PATH,
    L2WeightFile,
    QwenL2Artifact,
    QwenL2Error,
    QwenL2Pin,
    discover_l2_pin,
    fetch_l2_snapshot,
    inspect_l2_cache,
    inspect_l2_snapshot,
    l2_snapshot_path,
    load_l2_pin,
)


def __getattr__(name: str) -> Any:
    if name == "DeterministicFakeQwenBackend":
        from .fake_backend import DeterministicFakeQwenBackend

        return DeterministicFakeQwenBackend
    if name in {"CachingQwenBackend", "RealQwenBackend"}:
        from .real_backend import CachingQwenBackend, RealQwenBackend

        return {"CachingQwenBackend": CachingQwenBackend, "RealQwenBackend": RealQwenBackend}[
            name
        ]
    raise AttributeError(name)


__all__ = [
    "DEFAULT_PIN_PATH",
    "DEFAULT_L2_PIN_PATH",
    "MODEL_ID",
    "CachingQwenBackend",
    "QwenL1Artifact",
    "QwenL1Error",
    "QwenL1Pin",
    "QwenL1WeightError",
    "L2WeightFile",
    "QwenL2Artifact",
    "QwenL2Error",
    "QwenL2Pin",
    "RealQwenBackend",
    "DeterministicFakeQwenBackend",
    "discover_repo_revision",
    "discover_l2_pin",
    "fetch_l2_snapshot",
    "fetch_metadata_tokenizer",
    "inspect_cache",
    "inspect_l2_cache",
    "inspect_l2_snapshot",
    "l2_snapshot_path",
    "load_pin",
    "load_l2_pin",
    "profile_jsonl",
    "profile_records",
]
