"""Strict JSON decoding and immutable JSON objects at versioned boundaries."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .canonical import canonical_json


class BoundaryError(ValueError):
    """A classified boundary failure without echoing potentially secret payloads."""

    def __init__(self, stage: str, code: str, recovery: str = "repair the producing input") -> None:
        self.stage = stage
        self.code = code
        self.recovery = recovery
        super().__init__(f"stage={stage}; code={code}; recovery={recovery}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BoundaryError("json", "duplicate_key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise BoundaryError("json", "non_finite_number")


def decode_json(raw: bytes | str) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise BoundaryError("json", "invalid_encoding_or_document") from error


def object_fields(value: object, fields: set[str], stage: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise BoundaryError(stage, "missing_or_unknown_fields")
    return value


def text(value: object, stage: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise BoundaryError(stage, "invalid_text")
    if any(ord(character) < 32 for character in value):
        raise BoundaryError(stage, "control_character")
    return value


def digest(value: object, stage: str, *, length: int = 64) -> str:
    if not isinstance(value, str) or re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is None:
        raise BoundaryError(stage, "invalid_digest")
    return value


def unsigned(value: object, stage: str) -> int:
    if type(value) is not int or value < 0:
        raise BoundaryError(stage, "invalid_unsigned_integer")
    return value


def array(value: object, stage: str) -> list[Any]:
    if not isinstance(value, list):
        raise BoundaryError(stage, "expected_array")
    return value


def json_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


@dataclass(frozen=True)
class FrozenObject:
    """Store canonical bytes rather than a mutable dictionary in frozen dataclasses."""

    encoded: str = "{}"

    def __post_init__(self) -> None:
        value = decode_json(self.encoded)
        if not isinstance(value, dict) or canonical_json(value) != self.encoded:
            raise BoundaryError("frozen_object", "not_a_canonical_object")

    @classmethod
    def of(cls, value: Mapping[str, Any]) -> FrozenObject:
        return cls(canonical_json(value))

    def value(self) -> dict[str, Any]:
        value = decode_json(self.encoded)
        if not isinstance(value, dict):
            raise BoundaryError("frozen_object", "not_an_object")
        return value
