"""Explicit N/Z objective composition for the three v0 architecture families."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from torch import Tensor

from .losses import anchor_loss, listwise_rank_loss, normalized_successor_loss
from .s2_sdt import S2SDTOutput, S2SDTScorer
from .s2_simple import S2SimpleOutput


@dataclass(frozen=True)
class ObjectiveResult:
    total: Tensor
    rank: Tensor
    successor: Tensor | None = None
    anchor: Tensor | None = None


def scheme1_objective(scores: Tensor, target_index: int) -> ObjectiveResult:
    rank = listwise_rank_loss(scores, target_index)
    return ObjectiveResult(rank, rank)


def s2_simple_objective(
    output: S2SimpleOutput,
    target_index: int,
    *,
    variant: Literal["N", "Z"],
    successor_target: Tensor | None = None,
    lambda_z: float = 1.0,
) -> ObjectiveResult:
    rank = listwise_rank_loss(output.scores, target_index)
    if variant == "N":
        return ObjectiveResult(rank, rank)
    if successor_target is None:
        raise ValueError("S2-Simple Z requires a real successor target")
    successor = normalized_successor_loss(
        output.predicted_successors[target_index : target_index + 1], successor_target
    )
    return ObjectiveResult(rank + lambda_z * successor, rank, successor=successor)


def s2_sdt_objective(
    model: S2SDTScorer,
    output: S2SDTOutput,
    target_index: int,
    *,
    variant: Literal["N", "Z"],
    successor_target: Tensor | None = None,
    lambda_anchor: float = 1.0,
    lambda_z: float = 1.0,
) -> ObjectiveResult:
    rank = listwise_rank_loss(output.scores, target_index)
    anchor = anchor_loss(
        model.anchor_summary(output.state_world), output.frozen_state_summary.detach()
    )
    if variant == "N":
        return ObjectiveResult(rank + lambda_anchor * anchor, rank, anchor=anchor)
    if successor_target is None:
        raise ValueError("S2-SDT Z requires a real successor target")
    successor = normalized_successor_loss(
        output.predicted_world[target_index : target_index + 1], successor_target
    )
    return ObjectiveResult(
        rank + lambda_anchor * anchor + lambda_z * successor,
        rank,
        successor=successor,
        anchor=anchor,
    )
