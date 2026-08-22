"""Frozen first-round STPD v0 objective components."""

from __future__ import annotations

import torch
from torch import Tensor
from torch.nn import functional as F


def listwise_rank_loss(scores: Tensor, target_index: int) -> Tensor:
    """Cross entropy over one complete current candidate set."""

    if scores.ndim != 1 or scores.numel() == 0:
        raise ValueError("rank scores must be a non-empty vector")
    if not 0 <= target_index < scores.numel():
        raise ValueError("target index outside score vector")
    target = torch.tensor([target_index], device=scores.device, dtype=torch.long)
    return F.cross_entropy(scores.unsqueeze(0), target)


def normalized_successor_loss(predicted: Tensor, target: Tensor) -> Tensor:
    """Cosine distance used for S2-Simple Z and S2-SDT world supervision."""

    if predicted.shape != target.shape or predicted.numel() == 0:
        raise ValueError("predicted and target successor tensors must have the same shape")
    predicted_norm = F.normalize(predicted, dim=-1)
    target_norm = F.normalize(target.detach(), dim=-1)
    return (1.0 - (predicted_norm * target_norm).sum(dim=-1)).mean()


def anchor_loss(world_summary: Tensor, frozen_state_summary: Tensor) -> Tensor:
    """Keep learned world-state summaries tied to frozen semantic state features."""

    return normalized_successor_loss(world_summary, frozen_state_summary)
