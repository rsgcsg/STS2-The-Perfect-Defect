"""Portable, secret-free manifest for rebuilding STPD on an L2 compute host."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .qwen.l1 import QwenL1Artifact, QwenL1Pin

_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_SECRET_KEYS = frozenset({"api_key", "password", "secret", "token", "access_token"})


def _assert_portable(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS:
                raise ValueError(f"L2 handoff contains a secret-bearing key at {path}.{key}")
            _assert_portable(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_portable(item, path=f"{path}[{index}]")
    elif isinstance(value, str) and (
        value.startswith(("/", "file://")) or _WINDOWS_ABSOLUTE.match(value)
    ):
        raise ValueError(f"L2 handoff contains an absolute local path at {path}")


def build_l2_handoff(
    *,
    source_revision: str,
    uv_lock: Path,
    qwen_pin: QwenL1Pin,
    qwen_l1: QwenL1Artifact,
    environment: Mapping[str, Any],
    data_manifest: Path | None = None,
) -> dict[str, Any]:
    if not source_revision.strip() or not uv_lock.is_file():
        raise ValueError("L2 handoff requires source revision and uv.lock")
    qwen_pin.validate()
    qwen_l1.validate()
    data = None
    if data_manifest is not None:
        if not data_manifest.is_file():
            raise ValueError("data manifest does not exist")
        data = {
            "filename": data_manifest.name,
            "sha256": hashlib.sha256(data_manifest.read_bytes()).hexdigest(),
        }
    handoff = {
        "schema": "stpd/l2-handoff-v0",
        "source": {
            "repository": "https://github.com/rsgcsg/STS2-The-Perfect-Defect.git",
            "revision": source_revision,
            "python": ">=3.11,<3.12",
            "uv_lock_sha256": hashlib.sha256(uv_lock.read_bytes()).hexdigest(),
        },
        "qwen": {
            "model_id": qwen_pin.model_id,
            "revision": qwen_pin.repo_revision,
            "config_sha256": qwen_pin.config_sha256,
            "tokenizer_bundle_sha256": qwen_pin.tokenizer_bundle_sha256,
            "l1_files": [file.to_dict() for file in qwen_l1.files],
            "weights": "required_external_not_present_in_l1",
        },
        "environment": dict(environment),
        "data_manifest": data,
        "rebuild": [
            "git clone https://github.com/rsgcsg/STS2-The-Perfect-Defect.git",
            f"git checkout {source_revision}",
            "uv sync --frozen --all-extras",
            "uv run python tools/doctor.py --require-qwen-cache --qwen-cache <cache>",
        ],
        "non_claims": [
            "This manifest contains no Qwen weights, secrets, game files, or absolute paths.",
            "L1 identity and FakeQwen tests do not prove real Qwen representation or training.",
        ],
    }
    _assert_portable(handoff)
    return handoff
