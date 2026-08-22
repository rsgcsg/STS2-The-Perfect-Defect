"""Deterministic JSON and model-input safety helpers.

Research records retain exact runtime provenance, while model inputs must contain only
fair-player semantic facts.  This module keeps those two concerns visibly separate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any


class CanonicalizationError(ValueError):
    """Raised when a value cannot enter a deterministic research artifact."""


_FORBIDDEN_MODEL_KEYS = frozenset(
    {
        "bound_action_id",
        "snapshot_id",
        "mutation_request_id",
        "request_id",
        "runtime_instance_id",
        "process_id",
        "controller_lease_id",
        "native_object_id",
        "native_operand",
        "teacher_identity",
        "model_identity",
        "future_outcome",
        "draw_order",
        "hidden_rng",
    }
)


def to_json_value(value: Any) -> Any:
    """Convert supported immutable Python values to a JSON-compatible tree."""

    if is_dataclass(value) and not isinstance(value, type):
        return to_json_value(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("JSON object keys must be strings")
            converted[key] = to_json_value(item)
        return converted
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise CanonicalizationError("non-finite floats are not canonical JSON")
        return value
    raise CanonicalizationError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return UTF-8 stable JSON with no insignificant whitespace."""

    return json.dumps(
        to_json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def semantic_hash(value: Any) -> str:
    """Hash canonical semantic content without runtime-specific salt."""

    payload = canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def reject_model_input_leakage(value: Any, *, path: str = "$") -> None:
    """Fail when authority, runtime identity, hidden state, or labels enter model input."""

    tree = to_json_value(value)
    if isinstance(tree, dict):
        for key, item in tree.items():
            normalized = key.lower()
            if normalized in _FORBIDDEN_MODEL_KEYS or normalized.startswith("native_"):
                raise CanonicalizationError(f"forbidden model-input key at {path}.{key}")
            reject_model_input_leakage(item, path=f"{path}.{key}")
    elif isinstance(tree, list):
        for index, item in enumerate(tree):
            reject_model_input_leakage(item, path=f"{path}[{index}]")
