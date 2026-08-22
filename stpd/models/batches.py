"""Typed candidate-set and executed-transition batches."""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import ContractError


@dataclass(frozen=True)
class RankBatch:
    state_text: str
    action_texts: tuple[str, ...]
    target_index: int
    source_id: str

    def validate(self) -> None:
        if not self.state_text or not self.source_id or not self.action_texts:
            raise ContractError("rank batch requires state, source, and candidates")
        if not 0 <= self.target_index < len(self.action_texts):
            raise ContractError("rank target index is outside the candidate catalog")


@dataclass(frozen=True)
class DynamicsBatch:
    state_text: str
    action_text: str
    successor_text: str
    source_id: str

    def validate(self) -> None:
        if not all((self.state_text, self.action_text, self.successor_text, self.source_id)):
            raise ContractError("dynamics batch requires state, executed action, successor, source")
