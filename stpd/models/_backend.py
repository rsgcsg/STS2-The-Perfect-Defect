"""Narrow runtime checks for QwenBackend tensor outputs."""

from __future__ import annotations

from typing import Any

import torch
from torch import Tensor


def tensor(value: Any, *, name: str) -> Tensor:
    if not isinstance(value, Tensor):
        raise TypeError(f"{name} must be a torch.Tensor")
    return value


def sequence(value: Any, *, name: str) -> tuple[Tensor, Tensor]:
    if not isinstance(value, tuple) or len(value) != 2:
        raise TypeError(f"{name} must be (hidden, mask)")
    hidden, mask = value
    if not isinstance(hidden, Tensor) or not isinstance(mask, Tensor):
        raise TypeError(f"{name} hidden and mask must be torch.Tensor")
    if hidden.ndim != 3 or mask.ndim != 2 or hidden.shape[:2] != mask.shape:
        raise ValueError(f"{name} has incompatible hidden/mask shapes")
    return hidden, mask.to(dtype=torch.bool)


def masked_mean(hidden: Tensor, mask: Tensor) -> Tensor:
    weights = mask.to(dtype=hidden.dtype).unsqueeze(-1)
    return (hidden * weights).sum(dim=1) / weights.sum(dim=1).clamp_min(1.0)
