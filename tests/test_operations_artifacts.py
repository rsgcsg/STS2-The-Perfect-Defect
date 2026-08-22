from __future__ import annotations

import json
from pathlib import Path

import pytest

from stpd.artifacts import (
    ArtifactError,
    build_model_artifact_manifest,
    verify_model_artifact_manifest,
    write_model_artifact_manifest,
)
from stpd.l2_handoff import build_l2_handoff
from stpd.qwen.l1 import QwenL1Artifact, load_pin


def test_model_artifact_manifest_detects_tampering_and_traversal(tmp_path: Path) -> None:
    (tmp_path / "checkpoint.pt").write_bytes(b"checkpoint")
    manifest = build_model_artifact_manifest(
        tmp_path,
        artifact_id="artifact",
        source_revision="source",
        experiment_id="experiment",
        architecture_id="scheme1",
        input_profile="stpd-combat-v0-standard",
        backbone={"model": "fake"},
        files=("checkpoint.pt",),
        data_manifests=(),
        metrics={},
        compatibility={},
        non_claims=("engineering only",),
        created_at="2026-08-22T00:00:00+00:00",
    )
    path = tmp_path / "manifest.json"
    write_model_artifact_manifest(path, manifest)
    verify_model_artifact_manifest(tmp_path, path)
    (tmp_path / "checkpoint.pt").write_bytes(b"tampered")
    with pytest.raises(ArtifactError, match="checksum"):
        verify_model_artifact_manifest(tmp_path, path)
    with pytest.raises(ArtifactError, match="unsafe"):
        build_model_artifact_manifest(
            tmp_path,
            artifact_id="artifact",
            source_revision="source",
            experiment_id="experiment",
            architecture_id="scheme1",
            input_profile="standard",
            backbone={},
            files=("../escape",),
            data_manifests=(),
            metrics={},
            compatibility={},
            non_claims=("engineering only",),
        )


def test_l2_handoff_is_portable_and_records_no_weights(tmp_path: Path) -> None:
    pin = load_pin()
    lock = tmp_path / "uv.lock"
    lock.write_text("locked", encoding="utf-8")
    data = tmp_path / "manifest.json"
    data.write_text(json.dumps({"schema": "data"}), encoding="utf-8")
    artifact = QwenL1Artifact(
        pin.model_id,
        pin.repo_revision,
        pin.files,
        pin.special_tokens,
        pin.special_tokens_sha256,
        ("model.safetensors",),
    )
    handoff = build_l2_handoff(
        source_revision="a" * 40,
        uv_lock=lock,
        qwen_pin=pin,
        qwen_l1=artifact,
        environment={"host_kind": "managed_exact"},
        data_manifest=data,
    )
    rendered = json.dumps(handoff)
    assert handoff["qwen"]["weights"] == "required_external_not_present_in_l1"
    assert str(tmp_path) not in rendered
    assert handoff["data_manifest"]["filename"] == "manifest.json"
