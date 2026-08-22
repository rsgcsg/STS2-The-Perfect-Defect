#!/usr/bin/env python3
"""Run all v0 model families through FakeQwen, optimizer, checkpoint, and artifact IO."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Literal, cast

import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stpd.artifacts import (  # noqa: E402
    build_model_artifact_manifest,
    verify_model_artifact_manifest,
    write_model_artifact_manifest,
)
from stpd.canonical import semantic_hash  # noqa: E402
from stpd.models import (  # noqa: E402
    DynamicsBatch,
    RankBatch,
    S2SDTScorer,
    S2SimpleScorer,
    Scheme1Scorer,
)
from stpd.qwen.fake_backend import DeterministicFakeQwenBackend  # noqa: E402
from stpd.training import (  # noqa: E402
    CheckpointIdentity,
    CheckpointManager,
    TrainerState,
    V0Trainer,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        raise RuntimeError("pre-Qwen smoke requires a clean STPD checkout")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError(f"refusing to overwrite smoke output: {output}")
    output.mkdir(parents=True)
    torch.manual_seed(20260822)
    backend = DeterministicFakeQwenBackend(hidden_size=8, max_tokens=32)
    rank = RankBatch("state facts", ("play strike", "end turn"), 0, "engineering-smoke")
    dynamics = DynamicsBatch("state facts", "play strike", "successor facts", "engineering-smoke")
    definitions = (
        ("scheme1", Scheme1Scorer(backend, 8, head="linear"), "N", None),
        ("s2-simple", S2SimpleScorer(backend, 8), "Z", dynamics),
        (
            "s2-sdt",
            S2SDTScorer(backend, 8, model_dim=8, world_tokens=2, heads=2, layers=1),
            "Z",
            dynamics,
        ),
    )
    manager = CheckpointManager()
    results: dict[str, object] = {}
    artifact_files: list[str] = []
    for name, model, variant, successor in definitions:
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        trainer = V0Trainer(model, optimizer, variant=cast(Literal["N", "Z"], variant))
        metrics = trainer.train_step(rank, successor)
        identity = CheckpointIdentity(
            revision,
            "engineering-smoke-data",
            name,
            semantic_hash({"variant": variant}),
            "stpd-model-serialization-v0",
            "stpd-combat-v0-standard",
            backend.identity,
        )
        checkpoint = output / f"{name}.pt"
        manifest_path = manager.save(
            checkpoint,
            model=model,
            optimizer=optimizer,
            identity=identity,
            trainer_state=TrainerState(1, 1, int(successor is not None), 0),
        )
        restored = manager.load(
            checkpoint, model=model, optimizer=optimizer, expected_identity=identity
        )
        artifact_files.extend((checkpoint.name, manifest_path.name))
        results[name] = {"metrics": metrics.__dict__, "restored": restored.__dict__}
    manifest = build_model_artifact_manifest(
        output,
        artifact_id="preqwen-fake-engineering-smoke",
        source_revision=revision,
        experiment_id="preqwen-fake-engineering-smoke",
        architecture_id="scheme1+s2-simple+s2-sdt",
        input_profile="stpd-combat-v0-standard",
        backbone=backend.identity.__dict__,
        files=artifact_files,
        data_manifests=[],
        metrics=results,
        compatibility={"device": "cpu", "backend": "deterministic_fake"},
        non_claims=(
            "FakeQwen is a deterministic engineering test double, not a scientific control.",
            "One optimizer step does not prove learning or model quality.",
        ),
    )
    manifest_path = output / "model-artifact-manifest.json"
    write_model_artifact_manifest(manifest_path, manifest)
    verify_model_artifact_manifest(output, manifest_path)
    report = {
        "schema": "stpd/pre-qwen-smoke-v0",
        "status": "pass",
        "source_revision": revision,
        "families": results,
        "artifact_manifest": manifest_path.name,
        "non_claims": manifest["non_claims"],
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "pass", "output": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
