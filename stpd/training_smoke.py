from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import time
from typing import Any, Mapping

from sts2_headless import FiniteActionView, ManagedPlayerEnvironment

from .linear_q import LinearQ, combat_reward


def source_identity(root: Path) -> dict[str, Any]:
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()
    return {"revision": revision, "worktree": "clean" if not status else "dirty"}


def driver_command(headless: Path, candidate: Path) -> list[str]:
    return ["node", str(headless / "tools" / "managed-pe-driver.mjs"), "--candidate", str(candidate)]


def action_list(snapshot: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return list(FiniteActionView.from_snapshot(snapshot).actions)


def run_episode(
    environment: ManagedPlayerEnvironment,
    seed: str,
    model: LinearQ,
    rng: random.Random,
    *,
    train: bool,
    epsilon: float,
    max_actions: int,
) -> dict[str, Any]:
    snapshot = environment.reset(seed)
    total_reward = 0.0
    losses = []
    combat_decisions = 0
    delivered = 0
    inference_seconds = 0.0
    step_seconds = 0.0
    for _ in range(max_actions):
        if snapshot.get("interaction", {}).get("kind") == "game_over":
            break
        actions = action_list(snapshot)
        if not actions:
            break
        combat = snapshot.get("interaction", {}).get("kind") == "combat_turn"
        inference_started = time.perf_counter()
        selected = model.choose(snapshot, actions, rng, epsilon if train and combat else 0.0) \
            if combat else actions[0]
        inference_seconds += time.perf_counter() - inference_started
        step_started = time.perf_counter()
        receipt = environment.step(selected["bound_action_id"], snapshot["snapshot_id"])
        step_seconds += time.perf_counter() - step_started
        if receipt.get("delivery") != "delivered" or receipt.get("successor") is None:
            raise RuntimeError(f"Environment delivery failed: {receipt.get('delivery')}:{receipt.get('reason_code')}")
        successor = receipt["successor"]
        delivered += 1
        if combat:
            combat_decisions += 1
            reward = combat_reward(snapshot, successor)
            total_reward += reward
            if train:
                next_actions = action_list(successor) \
                    if successor.get("interaction", {}).get("kind") == "combat_turn" else []
                losses.append(model.update(snapshot, selected, reward, successor, next_actions))
        snapshot = successor
    persistent = snapshot.get("persistent", {}).get("content", {})
    surface = snapshot.get("interaction", {}).get("content", {}).get("surface", {})
    return {
        "seed": seed,
        "terminal": snapshot.get("interaction", {}).get("kind"),
        "victory": surface.get("victory") is True,
        "floor": persistent.get("run", {}).get("floor", 0),
        "hp": persistent.get("player", {}).get("hp", 0),
        "delivered": delivered,
        "combat_decisions": combat_decisions,
        "shaped_return": total_reward,
        "mean_td_loss": sum(losses) / len(losses) if losses else None,
        "inference_seconds": inference_seconds,
        "step_seconds": step_seconds,
    }


def summarize(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "episodes": len(episodes),
        "terminal_episodes": sum(episode["terminal"] == "game_over" for episode in episodes),
        "victories": sum(episode["victory"] for episode in episodes),
        "mean_floor": sum(episode["floor"] for episode in episodes) / len(episodes),
        "mean_shaped_return": sum(episode["shaped_return"] for episode in episodes) / len(episodes),
        "delivered": sum(episode["delivered"] for episode in episodes),
        "combat_decisions": sum(episode["combat_decisions"] for episode in episodes),
        "mean_td_loss": sum(
            episode["mean_td_loss"] for episode in episodes if episode["mean_td_loss"] is not None
        ) / max(1, sum(episode["mean_td_loss"] is not None for episode in episodes)),
        "inference_seconds": sum(episode["inference_seconds"] for episode in episodes),
        "host_step_wait_seconds": sum(episode["step_seconds"] for episode in episodes),
    }


def learning_verdict(
    baseline: Mapping[str, Any], trained: Mapping[str, Any]
) -> dict[str, Any]:
    terminal_complete = (
        baseline["terminal_episodes"] == baseline["episodes"]
        and trained["terminal_episodes"] == trained["episodes"]
    )
    improved_floor = trained["mean_floor"] > baseline["mean_floor"]
    improved_return = trained["mean_shaped_return"] > baseline["mean_shaped_return"]
    return {
        "status": "learning_smoke_pass"
        if terminal_complete and improved_floor and improved_return
        else "learning_smoke_failed",
        "terminal_complete": terminal_complete,
        "improved_mean_floor": improved_floor,
        "improved_mean_shaped_return": improved_return,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Independent real learner integration smoke.")
    parser.add_argument("--headless", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--train-episodes", type=int, default=30)
    parser.add_argument("--eval-episodes", type=int, default=8)
    parser.add_argument("--max-actions", type=int, default=600)
    parser.add_argument("--epsilon", type=float, default=0.25)
    parser.add_argument("--output", default=".local/evidence/training-smoke/report.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    headless = Path(args.headless).resolve()
    candidate = Path(args.candidate).resolve()
    model = LinearQ()
    rng = random.Random(731_2026)
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    with ManagedPlayerEnvironment(driver_command(headless, candidate)) as environment:
        provenance = environment.ready
        training = [
            run_episode(
                environment,
                f"STPDTRAIN{index + 1:04d}",
                model,
                rng,
                train=True,
                epsilon=args.epsilon,
                max_actions=args.max_actions,
            )
            for index in range(args.train_episodes)
        ]
        evaluation_seeds = [f"STPDEVAL{index + 1:04d}" for index in range(args.eval_episodes)]
        baseline = [
            run_episode(
                environment,
                seed,
                LinearQ(),
                random.Random(10_000 + index),
                train=False,
                epsilon=1.0,
                max_actions=args.max_actions,
            )
            for index, seed in enumerate(evaluation_seeds)
        ]
        trained = [
            run_episode(
                environment,
                seed,
                model,
                random.Random(20_000 + index),
                train=False,
                epsilon=0.0,
                max_actions=args.max_actions,
            )
            for index, seed in enumerate(evaluation_seeds)
        ]
    wall_seconds = time.perf_counter() - wall_started
    cpu_seconds = time.process_time() - cpu_started
    training_summary = summarize(training)
    baseline_summary = summarize(baseline)
    trained_summary = summarize(trained)
    verdict = learning_verdict(baseline_summary, trained_summary)
    total_samples = training_summary["delivered"] + baseline_summary["delivered"] + trained_summary["delivered"]
    report = {
        "schema": "stpd/real-learner-smoke-1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": verdict["status"],
        "stpd": source_identity(root),
        "headless": provenance.get("headless"),
        "candidate_build": provenance.get("candidate_build"),
        "runtime_identity": provenance.get("runtime_identity"),
        "adapter_runtime_instance_id": provenance.get("adapter_runtime_instance_id"),
        "algorithm": model.to_dict(),
        "training": {"summary": training_summary, "episodes": training},
        "evaluation": {
            "fixed_seeds": evaluation_seeds,
            "random_initial": {"summary": baseline_summary, "episodes": baseline},
            "trained_frozen": {"summary": trained_summary, "episodes": trained},
            "verdict": verdict,
        },
        "pipeline": {
            "topology": "synchronous_external_python_actor_learner",
            "usable_samples": total_samples,
            "wall_seconds": wall_seconds,
            "usable_samples_per_second": total_samples / wall_seconds,
            "python_cpu_seconds": cpu_seconds,
            "policy_version_lag": 0,
            "discarded_samples": 0,
            "gpu": "not_used",
        },
        "resource_envelope": {
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
            "host_workers": 1,
            "learner_processes": 1,
        },
        "non_claims": [
            "This linear shaped-reward learner is an H1 integration smoke, not the planned Qwen STPD model.",
            "Candidate-only learning does not prove shipped Reference transfer.",
            "A single training seed and short run do not establish reproducible learning validity."
        ],
    }
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output.parent / "model.json").write_text(json.dumps(model.to_dict(), indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report_file": str(output),
        "training": training_summary,
        "baseline": baseline_summary,
        "trained": trained_summary,
        "pipeline": report["pipeline"],
    }, indent=2))
    if report["status"] != "learning_smoke_pass":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
