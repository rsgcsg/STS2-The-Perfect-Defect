from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
import torch

from stpd.contracts import ContractError, QwenIdentity
from stpd.qwen.l2 import (
    L2WeightFile,
    QwenL2Error,
    inspect_l2_snapshot,
    load_l2_pin,
)
from stpd.qwen.real_backend import CachingQwenBackend, RealQwenBackend, _masked_mean


def _scientific_identity(*, control: str = "pretrained") -> QwenIdentity:
    return QwenIdentity(
        model_id="Qwen/Qwen3-0.6B-Base",
        model_revision="d" * 40,
        tokenizer_revision="d" * 40,
        dtype="bfloat16",
        device="cuda:0",
        frozen=True,
        control=control,
        config_sha256="a" * 64,
        tokenizer_sha256="b" * 64,
        weights_sha256="c" * 64 if control == "pretrained" else None,
        random_seed=None if control == "pretrained" else 20260822,
        initialization_sha256=None if control == "pretrained" else "e" * 64,
        attention_implementation="eager",
        feature_dtype="float32",
        cache_mode="none",
        torch_version="test",
        transformers_version="test",
    )


class _CacheBackend:
    identity = _scientific_identity()
    device = torch.device("cpu")

    def __init__(self) -> None:
        self.calls = 0

    def _value(self, rows: int) -> torch.Tensor:
        self.calls += 1
        return torch.arange(rows * 4, dtype=torch.float32).reshape(rows, 4)

    def encode_joint(self, state_texts, action_texts):
        assert len(state_texts) == len(action_texts)
        return self._value(len(state_texts))

    def encode_state(self, state_texts, *, return_sequence):
        pooled = self._value(len(state_texts))
        if return_sequence:
            return pooled.unsqueeze(1), torch.ones((len(state_texts), 1), dtype=torch.bool)
        return pooled

    def embed_action_tokens(self, action_texts):
        pooled = self._value(len(action_texts))
        return pooled.unsqueeze(1), torch.ones((len(action_texts), 1), dtype=torch.bool)


def test_l2_pin_binds_exact_full_weight_identity(tmp_path: Path) -> None:
    pin = load_l2_pin()
    assert pin.model_id == "Qwen/Qwen3-0.6B-Base"
    assert pin.repo_revision == "da87bfb608c14b7cf20ba1ce41287e8de496c0cd"
    assert pin.weight_files == (
        L2WeightFile(
            "model.safetensors",
            1_192_135_096,
            "cd2a512003e2f9f3cd3c32a9c3573f820bb28c940f73c57b1ddaa983d9223eba",
        ),
    )
    with pytest.raises(QwenL2Error, match="missing pinned L2 files"):
        inspect_l2_snapshot(tmp_path, pin)


def test_scientific_identity_distinguishes_pretrained_and_random() -> None:
    _scientific_identity(control="pretrained").validate_scientific_v0()
    _scientific_identity(control="random").validate_scientific_v0()
    invalid = _scientific_identity(control="random")
    object.__setattr__(invalid, "random_seed", None)
    with pytest.raises(ContractError, match="requires a seed"):
        invalid.validate_scientific_v0()


def test_masked_mean_ignores_padding_and_rejects_empty_rows() -> None:
    hidden = torch.tensor([[[1.0, 3.0], [3.0, 5.0], [100.0, 100.0]]])
    mask = torch.tensor([[True, True, False]])
    torch.testing.assert_close(_masked_mean(hidden, mask), torch.tensor([[2.0, 4.0]]))
    with pytest.raises(QwenL2Error, match="empty token"):
        _masked_mean(hidden, torch.zeros_like(mask))


def test_memory_cache_is_checksum_keyed_and_returns_clones() -> None:
    backend = _CacheBackend()
    cache = CachingQwenBackend(cast(RealQwenBackend, backend))
    first = cache.encode_joint(["state"], ["action"])
    first.zero_()
    second = cache.encode_joint(["state"], ["action"])
    assert backend.calls == 1
    assert not torch.equal(first, second)
    manifest = cache.manifest()
    assert manifest["entry_count"] == 1
    assert manifest["total_bytes"] == 16
    assert len(manifest["entries_sha256"]) == 64
