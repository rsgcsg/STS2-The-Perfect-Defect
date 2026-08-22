from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
import torch
from torch import Tensor

from stpd.contracts import ContractError, QwenIdentity
from stpd.evaluation import evaluate_ranking
from stpd.models import DynamicsBatch, RankBatch, S2SimpleScorer, Scheme1Scorer
from stpd.training import CheckpointIdentity, CheckpointManager, TrainerState, V0Trainer


class _Backend:
    identity = QwenIdentity("fake", "rev", "tok", "float32", "cpu", True)

    def _vector(self, text: str) -> Tensor:
        digest = hashlib.sha256(text.encode()).digest()
        return torch.tensor([(digest[index] - 127.5) / 127.5 for index in range(8)])

    def encode_joint(self, state_texts, action_texts):
        return torch.stack(
            [
                self._vector(state + action)
                for state, action in zip(state_texts, action_texts, strict=True)
            ]
        )

    def encode_state(self, state_texts, *, return_sequence):
        pooled = torch.stack([self._vector(text) for text in state_texts])
        if return_sequence:
            return pooled.unsqueeze(1), torch.ones((len(state_texts), 1), dtype=torch.bool)
        return pooled

    def embed_action_tokens(self, action_texts):
        pooled = torch.stack([self._vector(text) for text in action_texts])
        return pooled.unsqueeze(1), torch.ones((len(action_texts), 1), dtype=torch.bool)


def _identity() -> CheckpointIdentity:
    return CheckpointIdentity(
        "source-sha",
        "data-hash",
        "scheme1-mlp",
        "config-hash",
        "stpd-model-serialization-v0",
        "stpd-combat-v0-standard",
        _Backend.identity,
    )


def test_trainer_enforces_executed_successor_alignment() -> None:
    torch.manual_seed(7)
    model = S2SimpleScorer(_Backend(), 8)
    trainer = V0Trainer(model, torch.optim.AdamW(model.parameters()), variant="Z")
    rank = RankBatch("state", ("a", "b"), 1, "teacher")
    dynamics = DynamicsBatch("state", "b", "next", "random")
    metrics = trainer.train_step(rank, dynamics)
    assert metrics.successor_loss is not None and metrics.candidate_count == 2
    with pytest.raises(ValueError, match="executed rank target"):
        trainer.train_step(rank, DynamicsBatch("state", "a", "next", "random"))


def test_checkpoint_round_trip_restores_model_optimizer_and_state(tmp_path: Path) -> None:
    torch.manual_seed(8)
    model = Scheme1Scorer(_Backend(), 8)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    trainer = V0Trainer(model, optimizer)
    trainer.train_step(RankBatch("state", ("a", "b"), 0, "teacher"))
    expected_parameters = copy.deepcopy(model.state_dict())
    path = tmp_path / "checkpoint.pt"
    state = TrainerState(1, 1, 0, 12)
    manager = CheckpointManager()
    manifest = manager.save(
        path,
        model=model,
        optimizer=optimizer,
        identity=_identity(),
        trainer_state=state,
    )
    assert manifest.is_file()
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
    loaded = manager.load(path, model=model, optimizer=optimizer, expected_identity=_identity())
    assert loaded == state
    for key, value in expected_parameters.items():
        assert torch.equal(model.state_dict()[key], value)

    wrong = copy.deepcopy(_identity())
    object.__setattr__(wrong, "data_manifest_hash", "different")
    with pytest.raises(ContractError, match="identity"):
        manager.load(path, model=model, optimizer=optimizer, expected_identity=wrong)


def test_checkpoint_detects_tampering(tmp_path: Path) -> None:
    model = Scheme1Scorer(_Backend(), 8)
    optimizer = torch.optim.AdamW(model.parameters())
    path = tmp_path / "checkpoint.pt"
    manager = CheckpointManager()
    manager.save(
        path,
        model=model,
        optimizer=optimizer,
        identity=_identity(),
        trainer_state=TrainerState(0, 0, 0, 0),
    )
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(ContractError, match="checksum"):
        manager.load(path, model=model, optimizer=optimizer, expected_identity=_identity())


def test_ranking_evaluator_reports_overall_and_source_metrics() -> None:
    batches = [
        RankBatch("s1", ("bad", "good"), 1, "teacher"),
        RankBatch("s2", ("good", "bad"), 0, "human"),
    ]

    def scorer(_state: str, actions: tuple[str, ...]) -> list[float]:
        return [1.0 if action == "good" else 0.0 for action in actions]

    metrics = evaluate_ranking(batches, scorer)
    assert metrics.top1_accuracy == 1.0
    assert metrics.mean_reciprocal_rank == 1.0
    assert set(metrics.by_source) == {"human", "teacher"}
