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


def __getattr__(name: str) -> Any:
    if name == "DeterministicFakeQwenBackend":
        from .fake_backend import DeterministicFakeQwenBackend

        return DeterministicFakeQwenBackend
    raise AttributeError(name)


__all__ = [
    "DEFAULT_PIN_PATH",
    "MODEL_ID",
    "QwenL1Artifact",
    "QwenL1Error",
    "QwenL1Pin",
    "QwenL1WeightError",
    "DeterministicFakeQwenBackend",
    "discover_repo_revision",
    "fetch_metadata_tokenizer",
    "inspect_cache",
    "load_pin",
    "profile_jsonl",
    "profile_records",
]
