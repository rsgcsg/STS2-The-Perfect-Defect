"""Identity-bound, atomic PyTorch checkpoint and resume support."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import torch
from torch import nn
from torch.optim import Optimizer

from ..canonical import canonical_json, semantic_hash
from ..contracts import ContractError, QwenIdentity


@dataclass(frozen=True)
class CheckpointIdentity:
    source_revision: str
    data_manifest_hash: str
    architecture_id: str
    config_hash: str
    serializer_version: str
    input_profile: str
    qwen: QwenIdentity

    def validate(self) -> None:
        for name, value in (
            ("source_revision", self.source_revision),
            ("data_manifest_hash", self.data_manifest_hash),
            ("architecture_id", self.architecture_id),
            ("config_hash", self.config_hash),
            ("serializer_version", self.serializer_version),
            ("input_profile", self.input_profile),
        ):
            if not value.strip():
                raise ContractError(f"checkpoint {name} must be non-empty")
        self.qwen.validate_v0()

    @property
    def identity_hash(self) -> str:
        self.validate()
        return semantic_hash(asdict(self))


@dataclass(frozen=True)
class TrainerState:
    optimizer_steps: int
    rank_examples: int
    dynamics_examples: int
    model_tokens: int


class CheckpointManager:
    """Saves tensor state separately from a reviewable checksum manifest."""

    def save(
        self,
        path: str | Path,
        *,
        model: nn.Module,
        optimizer: Optimizer,
        identity: CheckpointIdentity,
        trainer_state: TrainerState,
    ) -> Path:
        identity.validate()
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        payload = {
            "format": "stpd/pytorch-checkpoint-v0",
            "identity_hash": identity.identity_hash,
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "trainer_state": asdict(trainer_state),
            "torch_rng_state": torch.get_rng_state(),
        }
        torch.save(payload, temporary)
        os.replace(temporary, destination)
        checkpoint_sha = hashlib.sha256(destination.read_bytes()).hexdigest()
        manifest = {
            "schema": "stpd/checkpoint-manifest-v0",
            "identity": asdict(identity),
            "identity_hash": identity.identity_hash,
            "checkpoint_file": destination.name,
            "checkpoint_sha256": checkpoint_sha,
            "checkpoint_bytes": destination.stat().st_size,
            "trainer_state": asdict(trainer_state),
        }
        manifest_path = destination.with_suffix(destination.suffix + ".manifest.json")
        manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
        return manifest_path

    def load(
        self,
        path: str | Path,
        *,
        model: nn.Module,
        optimizer: Optimizer,
        expected_identity: CheckpointIdentity,
    ) -> TrainerState:
        source = Path(path)
        manifest_path = source.with_suffix(source.suffix + ".manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_identity.validate()
        if manifest["identity_hash"] != expected_identity.identity_hash:
            raise ContractError("checkpoint identity does not match the requested experiment")
        actual_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual_sha != manifest["checkpoint_sha256"]:
            raise ContractError("checkpoint checksum mismatch")
        payload = cast(dict[str, Any], torch.load(source, map_location="cpu", weights_only=True))
        if payload["format"] != "stpd/pytorch-checkpoint-v0":
            raise ContractError("unsupported checkpoint format")
        if payload["identity_hash"] != expected_identity.identity_hash:
            raise ContractError("checkpoint payload identity mismatch")
        model.load_state_dict(payload["model"])
        optimizer.load_state_dict(payload["optimizer"])
        torch.set_rng_state(payload["torch_rng_state"])
        return TrainerState(**payload["trainer_state"])

    def load_model_for_inference(
        self,
        path: str | Path,
        *,
        model: nn.Module,
        expected_identity: CheckpointIdentity,
    ) -> TrainerState:
        """Load only immutable model state after the normal identity/checksum gates.

        Live inference must not construct or restore an optimizer and must not
        mutate the process RNG state.  The tensor payload is still admitted by
        the same manifest, checksum, format, and experiment identity as resume.
        """

        source = Path(path)
        manifest_path = source.with_suffix(source.suffix + ".manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_identity.validate()
        if manifest["identity_hash"] != expected_identity.identity_hash:
            raise ContractError("checkpoint identity does not match the requested experiment")
        actual_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual_sha != manifest["checkpoint_sha256"]:
            raise ContractError("checkpoint checksum mismatch")
        payload = cast(dict[str, Any], torch.load(source, map_location="cpu", weights_only=True))
        if payload["format"] != "stpd/pytorch-checkpoint-v0":
            raise ContractError("unsupported checkpoint format")
        if payload["identity_hash"] != expected_identity.identity_hash:
            raise ContractError("checkpoint payload identity mismatch")
        model.load_state_dict(payload["model"], strict=True)
        return TrainerState(**payload["trainer_state"])
