"""Scheme 1 direct joint scoring over frozen state-action representations."""

from __future__ import annotations

from typing import cast

import torch
from torch import Tensor, nn

from ..contracts import ContractError, QwenBackend
from ._backend import tensor


def build_scheme1_head(hidden_size: int, *, head: str = "mlp") -> nn.Module:
    """One architecture authority for live-Qwen and precompiled-feature consumers."""
    if type(hidden_size) is not int or hidden_size < 1:
        raise ValueError("Scheme1 hidden size must be a positive integer")
    if head == "linear":
        return nn.Linear(hidden_size, 1)
    if head == "mlp":
        return nn.Sequential(nn.Linear(hidden_size, 256), nn.GELU(), nn.Linear(256, 1))
    raise ValueError("Scheme1 head must be linear or mlp")


class Scheme1Scorer(nn.Module):
    def __init__(self, backend: QwenBackend, hidden_size: int, *, head: str = "mlp") -> None:
        super().__init__()
        self.backend = backend
        self.head = build_scheme1_head(hidden_size, head=head)

    def forward(self, state_text: str, action_texts: tuple[str, ...]) -> Tensor:
        if not state_text or not action_texts:
            raise ContractError("Scheme1 requires one state and a non-empty candidate set")
        states = [state_text] * len(action_texts)
        encoded = tensor(self.backend.encode_joint(states, action_texts), name="encode_joint")
        if encoded.ndim != 2 or encoded.shape[0] != len(action_texts):
            raise ValueError("joint backend output must be [candidate, hidden]")
        return cast(Tensor, self.head(encoded)).squeeze(-1)

    def score(self, model_state: str, model_actions: tuple[str, ...]) -> list[float]:
        with torch.no_grad():
            return self.forward(model_state, model_actions).cpu().tolist()
