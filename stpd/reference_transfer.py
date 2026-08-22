"""Evaluate one frozen STPD policy on Managed Exact and shipped Reference Hosts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import time
from typing import Any, Mapping, Sequence

from .game_seed import require_canonical_game_seed
from .headless_client import activate_headless_client
from .linear_q import LinearQ
from .training_smoke import driver_command, run_episode, source_identity, summarize


def _reference_driver_command(
    headless: Path,
    game_dir: Path | None,
    experimental_connector: bool,
) -> list[str]:
    command = ["node", str(headless / "tools" / "reference-pe-driver.mjs")]
    if game_dir is not None:
        command.extend(["--game-dir", str(game_dir)])
    if experimental_connector:
        command.append("--experimental-connector")
    return command


def _episode_provenance_pass(episode: Mapping[str, Any]) -> bool:
    return (
        episode.get("episode_identity", {})
        .get("episode_provenance", {})
        .get("verdict") == "provenance_pass"
    )


def transfer_verdict(
    candidate: Sequence[Mapping[str, Any]],
    reference: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    same_seed_count = len(candidate) == len(reference) and all(
        left.get("seed") == right.get("seed")
        for left, right in zip(candidate, reference)
    )
    candidate_terminal = bool(candidate) and all(
        episode.get("terminal") == "game_over" for episode in candidate
    )
    reference_terminal = bool(reference) and all(
        episode.get("terminal") == "game_over" for episode in reference
    )
    provenance = all(_episode_provenance_pass(episode) for episode in [*candidate, *reference])
    delivered = all(int(episode.get("delivered", 0)) > 0 for episode in [*candidate, *reference])
    exact_outcomes = same_seed_count and all(
        left.get("victory") == right.get("victory")
        and left.get("floor") == right.get("floor")
        and left.get("hp") == right.get("hp")
        for left, right in zip(candidate, reference)
    )
    execution_pass = (
        same_seed_count
        and candidate_terminal
        and reference_terminal
        and provenance
        and delivered
    )
    return {
        "status": "reference_transfer_execution_pass"
        if execution_pass else "reference_transfer_failed",
        "same_seed_count": same_seed_count,
        "candidate_terminal_complete": candidate_terminal,
        "reference_terminal_complete": reference_terminal,
        "all_episode_provenance_pass": provenance,
        "all_episodes_delivered_actions": delivered,
        "exact_terminal_outcomes_match": exact_outcomes,
        "semantic_parity_claim": "exact_terminal_outcomes_match" if exact_outcomes else "not_claimed",
    }


def _evaluate(
    environment: Any,
    seeds: Sequence[str],
    model: LinearQ,
    max_actions: int,
) -> list[dict[str, Any]]:
    return [
        run_episode(
            environment,
            seed,
            model,
            random.Random(30_000 + index),
            train=False,
            epsilon=0.0,
            max_actions=max_actions,
            record_steps=True,
            verify_successor=True,
        )
        for index, seed in enumerate(seeds)
    ]


def _summary_or_none(episodes: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return summarize(list(episodes)) if episodes else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one Candidate-trained frozen policy on Managed Exact and shipped Reference."
    )
    parser.add_argument("--headless", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--seed", action="append", dest="seeds")
    parser.add_argument("--game-dir")
    parser.add_argument("--experimental-connector", action="store_true")
    parser.add_argument("--max-actions", type=int, default=600)
    parser.add_argument("--output", default=".local/evidence/reference-transfer/report.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    headless = Path(args.headless).resolve()
    candidate_path = Path(args.candidate).resolve()
    model_path = Path(args.model).resolve()
    model_bytes = model_path.read_bytes()
    model = LinearQ.from_dict(json.loads(model_bytes))
    seed_inputs = tuple(args.seeds or ("STPDXFER01", "STPDXFER02"))
    try:
        seeds = tuple(require_canonical_game_seed(seed) for seed in seed_inputs)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if not seeds or len(set(seeds)) != len(seeds):
        raise SystemExit("transfer seeds must be non-empty and unique")

    activate_headless_client(headless)
    from sts2_headless import ManagedPlayerEnvironment

    started = time.perf_counter()
    candidate_ready: Mapping[str, Any] | None = None
    reference_ready: Mapping[str, Any] | None = None
    candidate_episodes: list[dict[str, Any]] = []
    reference_episodes: list[dict[str, Any]] = []
    failure: dict[str, Any] | None = None
    stage = "managed"
    try:
        with ManagedPlayerEnvironment(driver_command(headless, candidate_path)) as environment:
            candidate_ready = environment.ready
            candidate_episodes = _evaluate(environment, seeds, model, args.max_actions)
        stage = "reference"
        reference_command = _reference_driver_command(
            headless,
            Path(args.game_dir).resolve() if args.game_dir else None,
            args.experimental_connector,
        )
        with ManagedPlayerEnvironment(reference_command) as environment:
            reference_ready = environment.ready
            reference_episodes = _evaluate(environment, seeds, model, args.max_actions)
    except Exception as error:
        failure = {
            "stage": stage,
            "type": type(error).__name__,
            "message": str(error),
        }
        details = getattr(error, "details", None)
        if isinstance(details, Mapping):
            failure["details"] = dict(details)

    verdict = transfer_verdict(candidate_episodes, reference_episodes)
    if failure is not None:
        verdict = {**verdict, "status": "reference_transfer_failed"}
    report = {
        "schema": "stpd/reference-transfer-smoke-1",
        "status": verdict["status"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stpd": source_identity(root),
        "frozen_policy": {
            "path": str(model_path),
            "sha256": hashlib.sha256(model_bytes).hexdigest(),
            "model": model.to_dict(),
        },
        "seeds": list(seeds),
        "managed": {
            "ready": candidate_ready,
            "summary": _summary_or_none(candidate_episodes),
            "episodes": candidate_episodes,
        },
        "reference": {
            "ready": reference_ready,
            "summary": _summary_or_none(reference_episodes),
            "episodes": reference_episodes,
        },
        "failure": failure,
        "verdict": verdict,
        "wall_seconds": time.perf_counter() - started,
        "non_claims": [
            "Execution transfer does not by itself prove policy quality or broad semantic parity.",
            "Exact terminal outcome parity is claimed only when the recorded per-seed outcomes match.",
            "This sequential smoke is not a throughput or resource-density benchmark.",
            "A partial report records evidence reached before a fail-closed driver or Host error.",
        ],
    }
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report_file": str(output),
        "managed": report["managed"]["summary"],
        "reference": report["reference"]["summary"],
        "verdict": verdict,
        "wall_seconds": report["wall_seconds"],
    }, indent=2))
    if report["status"] != "reference_transfer_execution_pass":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
