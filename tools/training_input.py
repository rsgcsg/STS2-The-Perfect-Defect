#!/usr/bin/env python3
"""Build, incrementally stage, and verify explicit STPD training inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from stpd.canonical import canonical_json
from stpd.data.training_handoff import (
    build_training_input,
    stage_training_input,
    verify_training_input,
)

ROOT = Path(__file__).resolve().parents[1]


def _json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _consumer_identity(entry_point: str) -> dict[str, str]:
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    ).strip()
    if status:
        raise RuntimeError("training-input build requires a clean exact STPD source")
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    return {
        "repository": "rsgcsg/STS2-The-Perfect-Defect",
        "source_revision": revision,
        "uv_lock_sha256": _sha256(ROOT / "uv.lock"),
        "entry_point": entry_point,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build")
    build.add_argument("--dataset", required=True, type=Path)
    build.add_argument("--store", required=True, type=Path)
    build.add_argument("--lane", required=True)
    build.add_argument("--serializer", required=True)
    build.add_argument("--input-profile", required=True)
    build.add_argument("--qwen-identity", required=True, type=Path)
    build.add_argument("--consumer-entry-point", required=True)
    build.add_argument("--feature-artifact", type=Path)

    stage = commands.add_parser("stage")
    stage.add_argument("--source-store", required=True, type=Path)
    stage.add_argument("--receiver-store", required=True, type=Path)
    stage.add_argument("--training-input-id", required=True)

    verify = commands.add_parser("verify")
    verify.add_argument("--store", required=True, type=Path)
    verify.add_argument("--training-input-id", required=True)

    arguments = parser.parse_args()
    if arguments.command == "build":
        result = build_training_input(
            dataset_directory=arguments.dataset,
            store_directory=arguments.store,
            lane=arguments.lane,
            serializer_version=arguments.serializer,
            input_profile=arguments.input_profile,
            qwen_identity=_json_object(arguments.qwen_identity),
            consumer_identity=_consumer_identity(arguments.consumer_entry_point),
            feature_artifact_directory=arguments.feature_artifact,
        )
    elif arguments.command == "stage":
        result = stage_training_input(
            source_store=arguments.source_store,
            receiver_store=arguments.receiver_store,
            training_input_id=arguments.training_input_id,
        )
    else:
        result = verify_training_input(arguments.store, arguments.training_input_id)
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
