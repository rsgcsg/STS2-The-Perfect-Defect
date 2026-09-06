from __future__ import annotations

import io

import pytest
import torch

from stpd.json_boundary import BoundaryError
from stpd.workers.checkpoint_codec import decode_checkpoint, encode_checkpoint


def test_tensor_tree_roundtrip_preserves_optimizer_keys_and_tuples() -> None:
    value = {
        "head": {"weight": torch.tensor([[1.0, 2.0]])},
        "optimizer": {"state": {0: {"step": torch.tensor(1.0)}}, "betas": (0.9, 0.999)},
        "flags": [True, None, "value", 17],
    }
    raw = encode_checkpoint(value)
    restored = decode_checkpoint(raw)
    assert torch.equal(restored["head"]["weight"], value["head"]["weight"])
    assert set(restored["optimizer"]["state"]) == {0}
    assert restored["optimizer"]["betas"] == (0.9, 0.999)
    assert restored["flags"] == value["flags"]
    assert raw == encode_checkpoint(value)


def test_pickle_and_malformed_or_non_finite_checkpoints_rejected() -> None:
    buffer = io.BytesIO()
    torch.save({"example": torch.tensor([1])}, buffer)
    for raw in (buffer.getvalue(), b"", b"STPDCKP1" + (999999999).to_bytes(8, "little") + b"x"):
        with pytest.raises(BoundaryError):
            decode_checkpoint(raw)
    with pytest.raises(BoundaryError, match="non_finite"):
        encode_checkpoint({"bad": torch.tensor([float("nan")])})
    with pytest.raises(BoundaryError, match="unsupported"):
        encode_checkpoint({"bad": object()})
