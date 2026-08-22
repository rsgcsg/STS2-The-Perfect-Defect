"""S2-Simple latent transition and value model."""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from ..contracts import ContractError, QwenBackend
from ._backend import tensor


@dataclass(frozen=True)
class S2SimpleOutput:
    scores: Tensor
    predicted_successors: Tensor
    state_latent: Tensor


class S2SimpleScorer(nn.Module):
    def __init__(self, backend: QwenBackend, hidden_size: int) -> None:
        super().__init__()
        self.backend = backend
        self.transition = nn.Sequential(
            nn.Linear(hidden_size * 2, hidden_size),
            nn.GELU(),
            nn.Linear(hidden_size, hidden_size),
        )
        self.value = nn.Sequential(nn.Linear(hidden_size, 256), nn.GELU(), nn.Linear(256, 1))

    def encode(self, texts: list[str]) -> Tensor:
        encoded = tensor(
            self.backend.encode_state(texts, return_sequence=False), name="encode_state"
        )
        if encoded.ndim != 2 or encoded.shape[0] != len(texts):
            raise ValueError("pooled backend output must be [batch, hidden]")
        return encoded

    def forward(self, state_text: str, action_texts: tuple[str, ...]) -> S2SimpleOutput:
        if not state_text or not action_texts:
            raise ContractError("S2-Simple requires one state and a non-empty candidate set")
        state = self.encode([state_text])
        actions = self.encode(list(action_texts))
        expanded_state = state.expand(actions.shape[0], -1)
        delta = self.transition(torch.cat((expanded_state, actions), dim=-1))
        predicted = F.normalize(expanded_state + delta, dim=-1)
        return S2SimpleOutput(self.value(predicted).squeeze(-1), predicted, state)

    def encode_successor(self, successor_texts: list[str]) -> Tensor:
        return F.normalize(self.encode(successor_texts), dim=-1)
