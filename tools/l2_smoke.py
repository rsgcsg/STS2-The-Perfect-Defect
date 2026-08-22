#!/usr/bin/env python3
"""Run full-weight Qwen inference, cache, and gradient-only v0 engineering smokes."""

from __future__ import annotations

import argparse
import gc
import json
import subprocess
import sys
from functools import partial
from pathlib import Path
from time import perf_counter
from typing import Any

import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stpd.models import S2SDTScorer, S2SimpleScorer, Scheme1Scorer  # noqa: E402
from stpd.models.objectives import (  # noqa: E402
    s2_sdt_objective,
    s2_simple_objective,
    scheme1_objective,
)
from stpd.qwen.l2 import l2_snapshot_path, load_l2_pin  # noqa: E402
from stpd.qwen.real_backend import CachingQwenBackend, RealQwenBackend  # noqa: E402


def _measure(
    device: torch.device,
    operation: Any,
    *args: Any,
) -> tuple[Any, dict[str, Any]]:
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(device)
    torch.cuda.synchronize(device)
    started = perf_counter()
    value = operation(*args)
    torch.cuda.synchronize(device)
    elapsed = perf_counter() - started
    return value, {
        "seconds": elapsed,
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
    }


def _gradient_summary(model: nn.Module) -> dict[str, Any]:
    gradients = [
        parameter.grad.detach().float().norm()
        for parameter in model.parameters()
        if parameter.requires_grad and parameter.grad is not None
    ]
    if not gradients:
        raise RuntimeError("trainable model produced no gradients")
    return {
        "trainable_parameters": sum(
            parameter.numel() for parameter in model.parameters() if parameter.requires_grad
        ),
        "gradient_tensor_count": len(gradients),
        "gradient_norm": float(torch.stack(gradients).norm().cpu()),
    }


def _model_smokes(backend: RealQwenBackend) -> dict[str, Any]:
    device = backend.device
    state = "[STPD_STATE version=v0 profile=standard]\nENERGY=3\nHAND=strike,defend"
    actions = (
        "[STPD_ACTION version=v0]\nKIND=play_card\nVISIBLE=strike",
        "[STPD_ACTION version=v0]\nKIND=end_turn",
    )
    successor = "[STPD_STATE version=v0 profile=standard]\nENERGY=2\nHAND=defend"
    results: dict[str, Any] = {}

    scheme1 = Scheme1Scorer(backend, backend.hidden_size, head="linear").to(device)
    output, runtime = _measure(device, scheme1, state, actions)
    objective = scheme1_objective(output, 0)
    objective.total.backward()
    results["scheme1"] = {
        "scores_shape": list(output.shape),
        "loss": float(objective.total.detach().cpu()),
        "runtime": runtime,
        "gradients": _gradient_summary(scheme1),
    }
    del scheme1, output, objective

    simple = S2SimpleScorer(backend, backend.hidden_size).to(device)
    output, runtime = _measure(device, simple, state, actions)
    successor_target = simple.encode_successor([successor])
    objective = s2_simple_objective(
        output,
        0,
        variant="Z",
        successor_target=successor_target,
    )
    objective.total.backward()
    results["s2-simple"] = {
        "scores_shape": list(output.scores.shape),
        "successor_shape": list(output.predicted_successors.shape),
        "loss": float(objective.total.detach().cpu()),
        "runtime": runtime,
        "gradients": _gradient_summary(simple),
    }
    del simple, output, objective, successor_target

    sdt = S2SDTScorer(backend, backend.hidden_size).to(device)
    output, runtime = _measure(device, sdt, state, actions)
    successor_target = sdt.target_world([successor])
    objective = s2_sdt_objective(
        sdt,
        output,
        0,
        variant="Z",
        successor_target=successor_target,
    )
    objective.total.backward()
    results["s2-sdt"] = {
        "scores_shape": list(output.scores.shape),
        "world_shape": list(output.predicted_world.shape),
        "loss": float(objective.total.detach().cpu()),
        "runtime": runtime,
        "gradients": _gradient_summary(sdt),
    }
    del sdt, output, objective, successor_target
    if not backend.parameters_frozen() or not backend.parameter_gradients_absent():
        raise RuntimeError("gradient smoke touched the frozen Qwen backbone")
    torch.cuda.empty_cache()
    return results


def _representation_smoke(backend: RealQwenBackend) -> dict[str, Any]:
    state = "state energy 3 hand strike defend"
    action = "play strike target enemy zero"
    joint, cold = _measure(backend.device, backend.encode_joint, [state], [action])
    repeated, warm = _measure(
        backend.device,
        backend.encode_joint,
        [state],
        [action],
    )
    if not torch.equal(joint, repeated):
        raise RuntimeError("repeated eager Qwen hidden extraction is not bit-deterministic")
    sequence, mask = backend.encode_state([state], return_sequence=True)
    embeddings, action_mask = backend.embed_action_tokens([action])

    cache = CachingQwenBackend(backend)
    cached_first, cache_fill = _measure(
        backend.device,
        cache.encode_joint,
        [state],
        [action],
    )
    cached_second, cache_hit = _measure(
        backend.device,
        cache.encode_joint,
        [state],
        [action],
    )
    if not torch.equal(joint, cached_first) or not torch.equal(cached_first, cached_second):
        raise RuntimeError("memory cache changed a frozen Qwen feature")

    profile_text = " ".join(["combat_state"] * 512)
    _, profile_runtime = _measure(
        backend.device,
        partial(backend.encode_state, return_sequence=False),
        [profile_text],
    )
    return {
        "joint_shape": list(joint.shape),
        "state_sequence_shape": list(sequence.shape),
        "state_mask_shape": list(mask.shape),
        "action_embedding_shape": list(embeddings.shape),
        "action_mask_shape": list(action_mask.shape),
        "deterministic_exact": True,
        "joint_cold": cold,
        "joint_warm_uncached": warm,
        "memory_cache_fill": cache_fill,
        "memory_cache_hit": cache_hit,
        "cache_manifest": cache.manifest(),
        "synthetic_profile": {
            "token_count": backend.token_lengths([profile_text])[0],
            "runtime": profile_runtime,
        },
    }


def _control(cache_dir: Path, control: str, random_seed: int) -> dict[str, Any]:
    pin = load_l2_pin()
    snapshot = l2_snapshot_path(cache_dir, pin)
    device = torch.device("cuda:0")
    torch.cuda.init()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(device)
    backend = RealQwenBackend(
        snapshot,
        control=control,  # type: ignore[arg-type]
        random_seed=random_seed if control == "random" else None,
        pin=pin,
    )
    report = {
        "runtime": backend.runtime_summary(),
        "representations": _representation_smoke(backend),
        "models": _model_smokes(backend),
        "frozen_parameters": backend.parameters_frozen(),
        "qwen_gradients_absent": backend.parameter_gradients_absent(),
        "process_peak_allocated_bytes": torch.cuda.max_memory_allocated(backend.device),
        "process_peak_reserved_bytes": torch.cuda.max_memory_reserved(backend.device),
    }
    del backend
    gc.collect()
    torch.cuda.empty_cache()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--random-seed", type=int, default=20260822)
    parser.add_argument(
        "--control",
        action="append",
        choices=("pretrained", "random"),
        dest="controls",
    )
    args = parser.parse_args()
    controls = args.controls or ["pretrained", "random"]
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError(f"refusing to overwrite L2 smoke evidence: {output}")
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True))
    results = {
        control: _control(args.cache_dir.expanduser(), control, args.random_seed)
        for control in controls
    }
    report = {
        "schema": "stpd/qwen-l2-engineering-smoke-v0",
        "status": "pass",
        "source_revision": revision,
        "source_dirty": dirty,
        "random_seed": args.random_seed,
        "controls": results,
        "non_claims": [
            "Synthetic forward/backward checks are engineering evidence, not learning results.",
            "No optimizer step, research dataset, checkpoint, Gold-test, or B6 run was used.",
            "Synthetic latency/cache measurements do not replace admitted-corpus B7 profiling.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "output": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
