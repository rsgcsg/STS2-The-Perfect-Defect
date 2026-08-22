"""Candidate-set optimizer for Scheme 1, S2-Simple, and S2-SDT."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from torch import nn
from torch.optim import Optimizer

from ..models import DynamicsBatch, RankBatch
from ..models.objectives import s2_sdt_objective, s2_simple_objective, scheme1_objective
from ..models.s2_sdt import S2SDTScorer
from ..models.s2_simple import S2SimpleScorer
from ..models.scheme1 import Scheme1Scorer


@dataclass(frozen=True)
class StepMetrics:
    total_loss: float
    rank_loss: float
    successor_loss: float | None
    anchor_loss: float | None
    candidate_count: int


class V0Trainer:
    def __init__(
        self,
        model: Scheme1Scorer | S2SimpleScorer | S2SDTScorer,
        optimizer: Optimizer,
        *,
        variant: Literal["N", "Z"] = "N",
        lambda_z: float = 1.0,
        lambda_anchor: float = 1.0,
        grad_clip_norm: float = 1.0,
    ) -> None:
        self.model = model
        self.optimizer = optimizer
        self.variant = variant
        self.lambda_z = lambda_z
        self.lambda_anchor = lambda_anchor
        self.grad_clip_norm = grad_clip_norm

    def train_step(self, rank: RankBatch, dynamics: DynamicsBatch | None = None) -> StepMetrics:
        rank.validate()
        if dynamics is not None:
            dynamics.validate()
            if dynamics.state_text != rank.state_text:
                raise ValueError("rank and dynamics state must identify the same decision")
            if dynamics.action_text != rank.action_texts[rank.target_index]:
                raise ValueError("dynamics action must be the executed rank target")
        self.model.train()
        self.optimizer.zero_grad(set_to_none=True)
        if isinstance(self.model, Scheme1Scorer):
            if dynamics is not None or self.variant != "N":
                raise ValueError("Scheme 1 uses rank-only N objective")
            result = scheme1_objective(
                self.model(rank.state_text, rank.action_texts), rank.target_index
            )
        elif isinstance(self.model, S2SimpleScorer):
            output = self.model(rank.state_text, rank.action_texts)
            successor = None
            if dynamics is not None:
                successor = self.model.encode_successor([dynamics.successor_text])
            result = s2_simple_objective(
                output,
                rank.target_index,
                variant=self.variant,
                successor_target=successor,
                lambda_z=self.lambda_z,
            )
        else:
            output = self.model(rank.state_text, rank.action_texts)
            successor = None
            if dynamics is not None:
                successor = self.model.target_world([dynamics.successor_text])
            result = s2_sdt_objective(
                self.model,
                output,
                rank.target_index,
                variant=self.variant,
                successor_target=successor,
                lambda_anchor=self.lambda_anchor,
                lambda_z=self.lambda_z,
            )
        result.total.backward()
        nn.utils.clip_grad_norm_(self.model.parameters(), self.grad_clip_norm)
        self.optimizer.step()
        if isinstance(self.model, S2SDTScorer):
            self.model.update_target()
        return StepMetrics(
            float(result.total.detach()),
            float(result.rank.detach()),
            None if result.successor is None else float(result.successor.detach()),
            None if result.anchor is None else float(result.anchor.detach()),
            len(rank.action_texts),
        )
