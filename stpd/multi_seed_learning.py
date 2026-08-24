"""Reproducible multi-seed learning gate on the Managed Exact Host."""

from __future__ import annotations

import argparse
import json
import random
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .game_seed import derive_game_seed
from .host_runtime_client import DEFAULT_HOST_RUNTIME, activate_host_runtime_client
from .linear_q import LinearQ
from .training_smoke import (
    driver_command,
    learning_verdict,
    run_episode,
    source_identity,
    summarize,
)


def _provenance_pass(episodes: Sequence[Mapping[str, Any]]) -> bool:
    return all(
        episode.get("episode_identity", {}).get("episode_provenance", {}).get("verdict")
        == "provenance_pass"
        for episode in episodes
    )


def multi_seed_verdict(trials: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    learning_passes = sum(
        trial.get("verdict", {}).get("status") == "learning_smoke_pass" for trial in trials
    )
    provenance = all(trial.get("provenance_pass") is True for trial in trials)
    terminal = all(trial.get("verdict", {}).get("terminal_complete") is True for trial in trials)
    return {
        "status": "multi_seed_learning_pass"
        if trials and learning_passes == len(trials) and provenance and terminal
        else "multi_seed_learning_failed",
        "trials": len(trials),
        "learning_passes": learning_passes,
        "all_episode_provenance_pass": provenance,
        "all_terminal_complete": terminal,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Train independent frozen policies and require improvement for every learner seed."
        )
    )
    parser.add_argument("--host-runtime", type=Path, default=DEFAULT_HOST_RUNTIME)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--learner-seed", action="append", type=int, dest="learner_seeds")
    parser.add_argument("--train-episodes", type=int, default=30)
    parser.add_argument("--eval-episodes", type=int, default=8)
    parser.add_argument("--max-actions", type=int, default=600)
    parser.add_argument("--epsilon", type=float, default=0.25)
    parser.add_argument("--output", default=".local/evidence/multi-seed-learning/report.json")
    args = parser.parse_args()
    if args.train_episodes < 1 or args.eval_episodes < 1 or args.max_actions < 1:
        raise SystemExit("episode and action counts must be positive")

    root = Path(__file__).resolve().parents[1]
    host_runtime = args.host_runtime.resolve()
    candidate = Path(args.candidate).resolve()
    learner_seeds = tuple(args.learner_seeds or (731_2026, 731_2027, 731_2028))
    if len(set(learner_seeds)) != len(learner_seeds):
        raise SystemExit("learner seeds must be unique")
    evaluation_seeds = [
        derive_game_seed("STPD_MULTI_EVAL", index + 1) for index in range(args.eval_episodes)
    ]
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)

    activate_host_runtime_client(host_runtime)
    from sts2_headless import ManagedPlayerEnvironment

    trials: list[dict[str, Any]] = []
    wall_started = time.perf_counter()
    with ManagedPlayerEnvironment(driver_command(host_runtime, candidate)) as environment:
        ready = environment.ready
        for trial_index, learner_seed in enumerate(learner_seeds):
            model = LinearQ()
            training_rng = random.Random(learner_seed)
            training_seeds = [
                derive_game_seed("STPD_MULTI_TRAIN", trial_index + 1, index + 1)
                for index in range(args.train_episodes)
            ]
            training = [
                run_episode(
                    environment,
                    seed,
                    model,
                    training_rng,
                    train=True,
                    epsilon=args.epsilon,
                    max_actions=args.max_actions,
                )
                for seed in training_seeds
            ]
            baseline = [
                run_episode(
                    environment,
                    seed,
                    LinearQ(),
                    random.Random(10_000 + index),
                    train=False,
                    epsilon=0.0,
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
            baseline_summary = summarize(baseline)
            trained_summary = summarize(trained)
            verdict = learning_verdict(baseline_summary, trained_summary)
            all_episodes = [*training, *baseline, *trained]
            model_file = output.parent / f"model-{learner_seed}.json"
            model_file.write_text(json.dumps(model.to_dict(), indent=2) + "\n", encoding="utf-8")
            trials.append(
                {
                    "learner_seed": learner_seed,
                    "training": {"summary": summarize(training), "episodes": training},
                    "baseline": {"summary": baseline_summary, "episodes": baseline},
                    "trained": {"summary": trained_summary, "episodes": trained},
                    "verdict": verdict,
                    "provenance_pass": _provenance_pass(all_episodes),
                    "model_file": str(model_file),
                    "model": model.to_dict(),
                }
            )

    verdict = multi_seed_verdict(trials)
    report = {
        "schema": "stpd/multi-seed-learning-1",
        "status": verdict["status"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stpd": source_identity(root),
        "managed_ready": ready,
        "configuration": {
            "learner_seeds": list(learner_seeds),
            "train_episodes": args.train_episodes,
            "evaluation_seeds": evaluation_seeds,
            "max_actions": args.max_actions,
            "epsilon": args.epsilon,
        },
        "trials": trials,
        "verdict": verdict,
        "wall_seconds": time.perf_counter() - wall_started,
        "non_claims": [
            "This proves a small independent learner can improve on fixed Managed Exact "
            "evaluation seeds.",
            "It does not prove shipped Reference transfer, victory, or production policy quality.",
            "The learner and reward remain STPD-owned; they do not define Host semantics.",
        ],
    }
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "report_file": str(output),
                "verdict": verdict,
                "trials": [
                    {
                        "learner_seed": trial["learner_seed"],
                        "baseline": trial["baseline"]["summary"],
                        "trained": trial["trained"]["summary"],
                        "verdict": trial["verdict"],
                        "model_file": trial["model_file"],
                    }
                    for trial in trials
                ],
            },
            indent=2,
        )
    )
    if report["status"] != "multi_seed_learning_pass":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
