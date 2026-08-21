"""Stable STS2 seed identities for reproducible external experiments."""

from __future__ import annotations

import hashlib


_UNAMBIGUOUS_ALPHABET = frozenset("0123456789ABCDEFGHJKLMNPQRSTUVWXYZ")


def derive_game_seed(*parts: object) -> str:
    """Derive a seed that STS2 canonicalization will preserve byte-for-byte."""
    material = "\0".join(str(part) for part in parts).encode("utf-8")
    return f"STPD{hashlib.sha256(material).hexdigest()[:28].upper()}"


def require_canonical_game_seed(value: str) -> str:
    seed = value.strip()
    if (
        not 1 <= len(seed) <= 64
        or seed != seed.upper()
        or any(character not in _UNAMBIGUOUS_ALPHABET for character in seed)
    ):
        raise ValueError(
            "Seed must be 1-64 uppercase unambiguous STS2 seed characters; "
            "derive a seed instead of relying on game-side canonicalization."
        )
    return seed
