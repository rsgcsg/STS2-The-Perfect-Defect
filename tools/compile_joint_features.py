#!/usr/bin/env python3
"""Compile exact frozen-Qwen pooled joint features on a CUDA training host."""

from __future__ import annotations

import argparse
import json

from stpd.qwen.feature_artifact import compile_joint_feature_artifact
from stpd.qwen.real_backend import RealQwenBackend


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--qwen-snapshot", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--micro-batch-size", type=int, default=1)
    parser.add_argument("--feature-batch-size", type=int, default=8)
    parser.add_argument("--serializer", default="stpd-model-serialization-v1")
    parser.add_argument("--input-profile", default="stpd-combat-v0-standard")
    arguments = parser.parse_args()
    backend = RealQwenBackend(
        arguments.qwen_snapshot,
        control="pretrained",
        device=arguments.device,
        micro_batch_size=arguments.micro_batch_size,
    )
    artifact = compile_joint_feature_artifact(
        dataset_directory=arguments.dataset,
        output_root=arguments.output_root,
        backend=backend,
        serializer_version=arguments.serializer,
        input_profile=arguments.input_profile,
        batch_size=arguments.feature_batch_size,
    )
    print(json.dumps({"status": "compiled", "artifact": str(artifact)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
