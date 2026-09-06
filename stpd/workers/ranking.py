"""Shared Scheme1 head training over immutable features; no store/provider/UI dependencies."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, cast

import numpy as np
import torch
from torch import Tensor, nn

from ..canonical import semantic_hash
from ..fullrun.features import LoadedFeatures
from ..json_boundary import BoundaryError
from .checkpoint_codec import decode_checkpoint, encode_checkpoint
from .contracts import TrainingConfig


def new_head(hidden_size: int, kind: str, seed: int, device: str = "cpu") -> nn.Module:
    from ..models.scheme1 import build_scheme1_head

    with torch.random.fork_rng(devices=[]):
        torch.random.default_generator.manual_seed(seed)
        head = build_scheme1_head(hidden_size, head=kind)
    return head.to(device=device, dtype=torch.float32)


class RankingEngine:
    def __init__(self, features: LoadedFeatures, config: TrainingConfig) -> None:
        self.config = config
        self.features = features
        self.train_indices = tuple(
            index for index, sample in enumerate(features.samples) if sample.split == "train"
        )
        if not self.train_indices:
            raise BoundaryError("training", "empty_training_split")
        self.total_steps = config.max_steps or config.epochs * len(self.train_indices)
        if self.total_steps > config.epochs * len(self.train_indices):
            raise BoundaryError("training", "step_budget_exceeds_epoch_plan")
        self.plan = []
        for epoch in range(config.epochs):
            indices = list(self.train_indices)
            random.Random(f"stpd-train-v1:{config.seed}:{epoch}").shuffle(indices)
            self.plan.extend(indices)
        self.labels = {index: features.samples[index].chosen_index for index in self.train_indices}
        if config.label_control == "permuted":
            buckets: dict[int, list[int]] = defaultdict(list)
            for index in self.train_indices:
                buckets[len(features.rows[index])].append(index)
            for count, indices in sorted(buckets.items()):
                values = [self.labels[index] for index in indices]
                random.Random(f"stpd-label-v1:{config.seed}:{count}").shuffle(values)
                self.labels.update(zip(indices, values, strict=True))
        self.data_identity = semantic_hash(
            {
                "feature_set": features.manifest.artifact_id,
                "plan": self.plan[: self.total_steps],
                "labels": self.labels,
            }
        )
        self.matrix = torch.tensor(
            np.array(features.matrix, copy=True),
            dtype=torch.float32,
            device=config.device,
            requires_grad=False,
        )
        self.head = new_head(features.matrix.shape[1], config.head, config.seed, config.device)
        self.optimizer = torch.optim.AdamW(
            self.head.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
        )
        self.step = 0

    def advance(self) -> float:
        if self.step >= self.total_steps:
            raise BoundaryError("training", "run_already_exhausted")
        sample_index = self.plan[self.step]
        rows = list(self.features.rows[sample_index])
        label = self.labels[sample_index]
        if self.config.candidate_order == "permuted":
            order = list(range(len(rows)))
            random.Random(f"stpd-candidates-v1:{self.config.seed}:{self.step}").shuffle(order)
            rows = [rows[index] for index in order]
            label = order.index(label)
        self.head.train()
        self.optimizer.zero_grad(set_to_none=True)
        logits = cast(Tensor, self.head(self.matrix[rows])).reshape(1, -1)
        loss = nn.functional.cross_entropy(logits, torch.tensor([label], device=self.config.device))
        if not bool(torch.isfinite(loss)):
            raise BoundaryError("training", "non_finite_loss")
        loss.backward()
        if any(
            parameter.grad is not None and not bool(torch.isfinite(parameter.grad).all())
            for parameter in self.head.parameters()
        ):
            raise BoundaryError("training", "non_finite_gradient")
        self.optimizer.step()
        if any(not bool(torch.isfinite(parameter).all()) for parameter in self.head.parameters()):
            raise BoundaryError("training", "non_finite_parameter")
        if self.matrix.grad is not None or self.matrix.requires_grad:
            raise BoundaryError("training", "frozen_feature_gradient")
        self.step += 1
        return float(loss.detach().cpu())

    def scores(self, sample_index: int) -> tuple[float, ...]:
        self.head.eval()
        with torch.no_grad():
            values = cast(Tensor, self.head(self.matrix[list(self.features.rows[sample_index])]))
            result = tuple(float(value) for value in values.reshape(-1).detach().cpu().tolist())
        if len(result) != len(self.features.samples[sample_index].action_keys):
            raise BoundaryError("model", "score_count_mismatch")
        return result

    def checkpoint(self) -> bytes:
        state = {
            "schema": "stpd/ranking-checkpoint-v1",
            "data_identity": self.data_identity,
            "config": self.config.to_dict(),
            "step": self.step,
            "total_steps": self.total_steps,
            "torch_version": str(torch.__version__),
            "head": self.head.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "cpu_rng": torch.get_rng_state(),
        }
        return encode_checkpoint(state)

    def restore(self, raw: bytes) -> None:
        state = decode_checkpoint(raw)
        if (
            not isinstance(state, dict)
            or state.get("schema") != "stpd/ranking-checkpoint-v1"
            or state.get("data_identity") != self.data_identity
            or state.get("config") != self.config.to_dict()
            or state.get("torch_version") != str(torch.__version__)
            or state.get("total_steps") != self.total_steps
            or type(state.get("step")) is not int
            or not 0 <= state["step"] <= self.total_steps
        ):
            raise BoundaryError("checkpoint", "resume_identity_mismatch")
        self.head.load_state_dict(state["head"], strict=True)
        self.optimizer.load_state_dict(state["optimizer"])
        if any(not bool(torch.isfinite(parameter).all()) for parameter in self.head.parameters()):
            raise BoundaryError("checkpoint", "non_finite_parameter")
        self.step = state["step"]
        # There is no stochastic forward layer. Order/label controls derive from exact
        # seed + step; restoring does not mutate a caller's process-global RNG.
        if not isinstance(state.get("cpu_rng"), Tensor):
            raise BoundaryError("checkpoint", "missing_rng_audit_state")

    def model_bytes(self) -> bytes:
        from safetensors.torch import save

        weights = {
            name: tensor.detach().cpu().contiguous()
            for name, tensor in self.head.state_dict().items()
        }
        return cast(bytes, save(weights))


def load_head(raw: bytes, hidden_size: int, config: TrainingConfig) -> nn.Module:
    from safetensors.torch import load

    weights: dict[str, Any] = load(raw)
    head = new_head(hidden_size, config.head, config.seed, config.device)
    head.load_state_dict(weights, strict=True)
    if any(not bool(torch.isfinite(parameter).all()) for parameter in head.parameters()):
        raise BoundaryError("model", "non_finite_parameter")
    head.eval()
    return head
