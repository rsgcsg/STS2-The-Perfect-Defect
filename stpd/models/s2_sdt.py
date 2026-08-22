"""S2-SDT learned world-token resampler, dynamics, and value model."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import cast

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from ..contracts import ContractError, QwenBackend
from ._backend import masked_mean, sequence


class StateResampler(nn.Module):
    def __init__(self, qwen_hidden: int, model_dim: int, world_tokens: int, heads: int) -> None:
        super().__init__()
        self.queries = nn.Parameter(torch.empty(world_tokens, model_dim))
        nn.init.normal_(self.queries, std=0.02)
        self.key_value = nn.Linear(qwen_hidden, model_dim)
        self.attention = nn.MultiheadAttention(model_dim, heads, batch_first=True)
        self.norm = nn.LayerNorm(model_dim)

    def forward(self, hidden: Tensor, mask: Tensor) -> Tensor:
        batch = hidden.shape[0]
        query = self.queries.unsqueeze(0).expand(batch, -1, -1)
        key_value = self.key_value(hidden)
        output, _ = self.attention(query, key_value, key_value, key_padding_mask=~mask)
        return cast(Tensor, self.norm(query + output))


@dataclass(frozen=True)
class S2SDTOutput:
    scores: Tensor
    state_world: Tensor
    predicted_world: Tensor
    frozen_state_summary: Tensor


class S2SDTScorer(nn.Module):
    def __init__(
        self,
        backend: QwenBackend,
        qwen_hidden: int,
        *,
        model_dim: int = 512,
        world_tokens: int = 32,
        heads: int = 8,
        layers: int = 2,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.world_tokens = world_tokens
        self.resampler = StateResampler(qwen_hidden, model_dim, world_tokens, heads)
        self.target_resampler = copy.deepcopy(self.resampler)
        self.target_resampler.requires_grad_(False)
        self.action_projection = nn.Linear(qwen_hidden, model_dim)
        layer = nn.TransformerEncoderLayer(
            model_dim,
            heads,
            dim_feedforward=model_dim * 4,
            batch_first=True,
            activation="gelu",
        )
        self.dynamics = nn.TransformerEncoder(layer, layers)
        self.world_norm = nn.LayerNorm(model_dim)
        self.value_query = nn.Parameter(torch.empty(1, 1, model_dim))
        nn.init.normal_(self.value_query, std=0.02)
        self.value_attention = nn.MultiheadAttention(model_dim, heads, batch_first=True)
        self.value = nn.Sequential(nn.Linear(model_dim, 256), nn.GELU(), nn.Linear(256, 1))
        self.anchor_projection = nn.Linear(model_dim, qwen_hidden)

    def _state(self, texts: list[str], *, target: bool = False) -> tuple[Tensor, Tensor]:
        hidden, mask = sequence(
            self.backend.encode_state(texts, return_sequence=True), name="encode_state"
        )
        resampler = self.target_resampler if target else self.resampler
        world = resampler(hidden, mask)
        return world, masked_mean(hidden, mask)

    def forward(self, state_text: str, action_texts: tuple[str, ...]) -> S2SDTOutput:
        if not state_text or not action_texts:
            raise ContractError("S2-SDT requires one state and a non-empty candidate set")
        state_world, frozen_summary = self._state([state_text])
        action_hidden, action_mask = sequence(
            self.backend.embed_action_tokens(list(action_texts)), name="embed_action_tokens"
        )
        action_tokens = self.action_projection(action_hidden)
        candidates = len(action_texts)
        world = state_world.expand(candidates, -1, -1)
        dynamics_input = torch.cat((world, action_tokens), dim=1)
        world_mask = torch.ones(
            (candidates, self.world_tokens), device=action_mask.device, dtype=torch.bool
        )
        encoded = self.dynamics(
            dynamics_input,
            src_key_padding_mask=~torch.cat((world_mask, action_mask), dim=1),
        )
        predicted = self.world_norm(world + encoded[:, : self.world_tokens])
        query = self.value_query.expand(candidates, -1, -1)
        pooled, _ = self.value_attention(query, predicted, predicted)
        scores = self.value(pooled[:, 0]).squeeze(-1)
        return S2SDTOutput(scores, state_world, predicted, frozen_summary)

    def target_world(self, successor_texts: list[str]) -> Tensor:
        with torch.no_grad():
            world, _ = self._state(successor_texts, target=True)
            return world

    def anchor_summary(self, state_world: Tensor) -> Tensor:
        return F.normalize(self.anchor_projection(state_world.mean(dim=1)), dim=-1)

    @torch.no_grad()
    def update_target(self, decay: float = 0.99) -> None:
        if not 0 <= decay < 1:
            raise ValueError("EMA decay must be in [0, 1)")
        for target, source in zip(
            self.target_resampler.parameters(), self.resampler.parameters(), strict=True
        ):
            target.mul_(decay).add_(source, alpha=1 - decay)
