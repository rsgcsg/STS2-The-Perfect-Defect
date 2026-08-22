"""Deterministic shape-only backend for Qwen pipeline wiring tests.

This is not a random-initialized Qwen control and has no scientific meaning. It
does not load weights, tokenizer files, or a model implementation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import torch
from torch import Tensor

from ..contracts import QwenBackend, QwenIdentity


class DeterministicFakeQwenBackend:
    """A deterministic CPU backend with the same tensor shapes as the Qwen port."""

    def __init__(self, hidden_size: int = 16, *, max_tokens: int = 64) -> None:
        if hidden_size <= 0:
            raise ValueError("hidden_size must be positive")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.hidden_size = hidden_size
        self.max_tokens = max_tokens
        self.identity = QwenIdentity(
            model_id="stpd/deterministic-fake-qwen",
            model_revision="deterministic-fake-v0",
            tokenizer_revision="deterministic-fake-tokenizer-v0",
            dtype="float32",
            device="cpu",
            frozen=True,
        )
        self.identity.validate_v0()

    def _vector(self, key: str) -> Tensor:
        values: list[float] = []
        block = 0
        while len(values) < self.hidden_size:
            digest = hashlib.sha256(f"stpd-fake-qwen-v0\0{key}\0{block}".encode()).digest()
            values.extend((byte / 127.5) - 1.0 for byte in digest)
            block += 1
        return torch.tensor(values[: self.hidden_size], dtype=torch.float32)

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return text.split() or ["<empty>"]

    def _sequence(self, texts: Sequence[str]) -> tuple[Tensor, Tensor]:
        if not texts:
            raise ValueError("fake backend requires a non-empty batch")
        token_lists = [self._tokens(text) for text in texts]
        longest = max(len(tokens) for tokens in token_lists)
        if longest > self.max_tokens:
            raise ValueError(
                f"fake tokenizer input has {longest} tokens; max_tokens={self.max_tokens}"
            )
        hidden = torch.zeros((len(texts), longest, self.hidden_size), dtype=torch.float32)
        mask = torch.zeros((len(texts), longest), dtype=torch.bool)
        for row, tokens in enumerate(token_lists):
            for column, token in enumerate(tokens):
                hidden[row, column] = self._vector(f"token:{column}:{token}")
                mask[row, column] = True
        return hidden, mask

    def encode_joint(self, state_texts: Sequence[str], action_texts: Sequence[str]) -> Tensor:
        """Return one deterministic pooled vector per state/action pair."""

        if len(state_texts) != len(action_texts) or not state_texts:
            raise ValueError("joint state/action batches must be non-empty and equally sized")
        return torch.stack(
            [
                self._vector(f"joint:{state}\0{action}")
                for state, action in zip(state_texts, action_texts, strict=True)
            ],
            dim=0,
        )

    def encode_state(
        self,
        state_texts: Sequence[str],
        *,
        return_sequence: bool,
    ) -> Tensor | tuple[Tensor, Tensor]:
        """Return pooled state vectors or padded token vectors plus a boolean mask."""

        hidden, mask = self._sequence(state_texts)
        if return_sequence:
            return hidden, mask
        weights = mask.to(dtype=hidden.dtype).unsqueeze(-1)
        return (hidden * weights).sum(dim=1) / weights.sum(dim=1).clamp_min(1.0)

    def embed_action_tokens(self, action_texts: Sequence[str]) -> tuple[Tensor, Tensor]:
        """Return padded action-token vectors and a boolean non-padding mask."""

        return self._sequence(action_texts)


def assert_fake_backend_port(backend: DeterministicFakeQwenBackend) -> None:
    """Runtime assertion used by tests and small pipeline probes."""

    if not isinstance(backend, QwenBackend):
        raise TypeError("deterministic fake backend does not satisfy QwenBackend")
