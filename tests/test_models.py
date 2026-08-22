from __future__ import annotations

import hashlib

import pytest
import torch
from torch import Tensor

from stpd.contracts import QwenIdentity
from stpd.models import (
    DynamicsBatch,
    RankBatch,
    S2SDTScorer,
    S2SimpleScorer,
    Scheme1Scorer,
    listwise_rank_loss,
    s2_sdt_objective,
    s2_simple_objective,
    scheme1_objective,
)


class _TestBackend:
    def __init__(self, hidden_size: int = 16) -> None:
        self.hidden_size = hidden_size
        self.identity = QwenIdentity("test", "rev", "tok", "float32", "cpu", True)

    def _vector(self, text: str) -> Tensor:
        digest = hashlib.sha256(text.encode()).digest()
        return torch.tensor(
            [(digest[index] / 127.5) - 1.0 for index in range(self.hidden_size)],
            dtype=torch.float32,
        )

    def encode_joint(self, state_texts, action_texts):
        return torch.stack(
            [
                self._vector(f"{state}\0{action}")
                for state, action in zip(state_texts, action_texts, strict=True)
            ]
        )

    def encode_state(self, state_texts, *, return_sequence):
        pooled = torch.stack([self._vector(text) for text in state_texts])
        if not return_sequence:
            return pooled
        hidden = torch.stack((pooled, pooled.roll(1, dims=-1)), dim=1)
        return hidden, torch.ones(hidden.shape[:2], dtype=torch.bool)

    def embed_action_tokens(self, action_texts):
        pooled = torch.stack([self._vector(text) for text in action_texts])
        hidden = torch.stack((pooled, pooled.roll(2, dims=-1), pooled.roll(3, dims=-1)), dim=1)
        return hidden, torch.ones(hidden.shape[:2], dtype=torch.bool)


def test_batch_contracts_fail_closed() -> None:
    RankBatch("state", ("a", "b"), 1, "teacher").validate()
    DynamicsBatch("state", "a", "successor", "random").validate()
    with pytest.raises(Exception, match="target index"):
        RankBatch("state", ("a",), 2, "teacher").validate()


def test_scheme1_scores_complete_catalog_and_backpropagates() -> None:
    torch.manual_seed(1)
    model = Scheme1Scorer(_TestBackend(), 16, head="mlp")
    scores = model("state", ("play", "end"))
    assert scores.shape == (2,)
    objective = scheme1_objective(scores, 1)
    objective.total.backward()
    assert any(parameter.grad is not None for parameter in model.parameters())
    assert model("state", ("play", "end")).shape == (2,)


def test_listwise_loss_rejects_flattened_or_invalid_catalog() -> None:
    assert listwise_rank_loss(torch.tensor([0.0, 1.0]), 1).item() > 0
    with pytest.raises(ValueError, match="non-empty vector"):
        listwise_rank_loss(torch.empty((0, 1)), 0)


def test_s2_simple_n_and_z_use_only_executed_successor() -> None:
    torch.manual_seed(2)
    backend = _TestBackend()
    model = S2SimpleScorer(backend, 16)
    output = model("state", ("play", "end"))
    assert output.scores.shape == (2,) and output.predicted_successors.shape == (2, 16)
    n = s2_simple_objective(output, 0, variant="N")
    successor = model.encode_successor(["successor"])
    z = s2_simple_objective(output, 0, variant="Z", successor_target=successor)
    assert n.successor is None and z.successor is not None and z.total >= z.rank
    with pytest.raises(ValueError, match="real successor"):
        s2_simple_objective(output, 0, variant="Z")


def test_s2_sdt_shapes_objectives_ema_and_gradients() -> None:
    torch.manual_seed(3)
    backend = _TestBackend()
    model = S2SDTScorer(backend, 16, model_dim=16, world_tokens=4, heads=4, layers=2)
    output = model("state", ("play", "end"))
    assert output.scores.shape == (2,)
    assert output.predicted_world.shape == (2, 4, 16)
    target = model.target_world(["successor"])
    n = s2_sdt_objective(model, output, 1, variant="N")
    z = s2_sdt_objective(model, output, 1, variant="Z", successor_target=target)
    assert n.anchor is not None and n.successor is None
    assert z.anchor is not None and z.successor is not None
    z.total.backward()
    assert any(parameter.grad is not None for parameter in model.resampler.parameters())
    before = next(model.target_resampler.parameters()).clone()
    with torch.no_grad():
        next(model.resampler.parameters()).add_(1.0)
    model.update_target(0.5)
    after = next(model.target_resampler.parameters())
    assert not torch.equal(before, after)
