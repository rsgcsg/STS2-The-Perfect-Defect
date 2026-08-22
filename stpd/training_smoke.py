from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import time
from typing import Any, Mapping
from uuid import uuid4

from .game_seed import derive_game_seed
from .headless_client import activate_headless_client
from .linear_q import LinearQ, combat_reward


class EpisodeExecutionError(RuntimeError):
    def __init__(self, message: str, details: Mapping[str, Any]):
        super().__init__(message)
        self.details = dict(details)


def _snapshot_marker(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.get("snapshot_id"),
        "sequence": snapshot.get("sequence"),
        "status": snapshot.get("status"),
        "interaction_kind": snapshot.get("interaction", {}).get("kind"),
        "interaction_stage": snapshot.get("interaction", {}).get("stage"),
        "bound_action_count": len(snapshot.get("bound_actions", {}).get("actions", [])),
    }


def _same_session(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_session = left.get("session", {})
    right_session = right.get("session", {})
    return all(
        left_session.get(key) == right_session.get(key)
        for key in ("runtime_instance_id", "environment_fingerprint")
    )


def _observe_until_stable(
    environment: Any,
    snapshot: Mapping[str, Any],
    *,
    timeout_seconds: float = 20.0,
) -> tuple[Mapping[str, Any], int]:
    current = snapshot
    advances = 0
    deadline = time.monotonic() + timeout_seconds
    while current.get("status") == "settling":
        if time.monotonic() >= deadline:
            raise EpisodeExecutionError(
                "Environment did not leave settling within the bounded supervision window.",
                {"last_observation": _snapshot_marker(current)},
            )
        time.sleep(0.02)
        observed = environment.observe()
        if not _same_session(current, observed):
            raise EpisodeExecutionError(
                "Environment identity changed while supervising settling.",
                {
                    "before": _snapshot_marker(current),
                    "observed": _snapshot_marker(observed),
                },
            )
        if observed.get("snapshot_id") != current.get("snapshot_id"):
            advances += 1
        current = observed
    return current, advances


def source_identity(root: Path) -> dict[str, Any]:
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()
    return {"revision": revision, "worktree": "clean" if not status else "dirty"}


def driver_command(headless: Path, candidate: Path) -> list[str]:
    return ["node", str(headless / "tools" / "managed-pe-driver.mjs"), "--candidate", str(candidate)]


def action_list(snapshot: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    catalog = snapshot.get("bound_actions")
    if not isinstance(catalog, Mapping) or catalog.get("status") != "complete":
        raise RuntimeError("Snapshot does not contain a complete finite BoundAction projection.")
    actions = catalog.get("actions")
    if not isinstance(actions, list):
        raise RuntimeError("Snapshot BoundActions must be a list.")
    ids = [str(action.get("bound_action_id")) for action in actions]
    if any(identifier in {"None", ""} for identifier in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("Snapshot contains invalid or duplicate BoundAction identities.")
    return list(actions)


def _referent_descriptor(snapshot: Mapping[str, Any], referent_id: Any) -> Mapping[str, Any] | None:
    if referent_id is None:
        return None
    referent = next(
        (item for item in snapshot.get("referents", []) if item.get("referent_id") == referent_id),
        None,
    )
    if not isinstance(referent, Mapping):
        return {"missing_referent": True}
    properties = referent.get("properties", {})
    stable_properties = {
        key: properties[key]
        for key in (
            "definition_id", "name", "type", "cost", "rarity", "is_upgraded",
            "target_type", "point_type", "row", "col", "option_id",
        )
        if isinstance(properties, Mapping) and key in properties
    }
    return {
        "role": referent.get("role"),
        "kind": referent.get("kind"),
        "label": referent.get("label"),
        "properties": stable_properties,
    }


def action_descriptor(snapshot: Mapping[str, Any], action: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "verb": action.get("verb"),
        "label": action.get("label"),
        "subject": _referent_descriptor(snapshot, action.get("subject_referent_id")),
        "arguments": [
            {
                "role": argument.get("role"),
                "referent": _referent_descriptor(snapshot, argument.get("referent_id")),
            }
            for argument in action.get("arguments", [])
        ],
    }


def _referent_policy_descriptor(
    snapshot: Mapping[str, Any], referent_id: Any
) -> Mapping[str, Any] | None:
    if referent_id is None:
        return None
    referent = next(
        (item for item in snapshot.get("referents", []) if item.get("referent_id") == referent_id),
        None,
    )
    if not isinstance(referent, Mapping):
        return {"missing_referent": True}
    properties = referent.get("properties", {})
    stable_properties = {
        key: properties[key]
        for key in (
            "definition_id", "type", "cost", "rarity", "is_upgraded",
            "target_type", "point_type", "row", "col", "option_id", "index",
        )
        if isinstance(properties, Mapping) and key in properties
    }
    return {
        "role": referent.get("role"),
        "kind": referent.get("kind"),
        "properties": stable_properties,
    }


def action_policy_descriptor(
    snapshot: Mapping[str, Any], action: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a strategy-free ordering key without localized presentation text."""
    return {
        "verb": action.get("verb"),
        "subject": _referent_policy_descriptor(snapshot, action.get("subject_referent_id")),
        "arguments": [
            {
                "role": argument.get("role"),
                "referent": _referent_policy_descriptor(snapshot, argument.get("referent_id")),
            }
            for argument in action.get("arguments", [])
        ],
    }


def _ordered_actions(
    snapshot: Mapping[str, Any], actions: list[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    return sorted(
        actions,
        key=lambda action: json.dumps(
            action_policy_descriptor(snapshot, action), sort_keys=True, separators=(",", ":")
        ),
    )


def _subject_role(snapshot: Mapping[str, Any], action: Mapping[str, Any]) -> str | None:
    referent_id = action.get("subject_referent_id")
    if referent_id is None:
        return None
    referent = next(
        (item for item in snapshot.get("referents", []) if item.get("referent_id") == referent_id),
        None,
    )
    return str(referent.get("role")) if isinstance(referent, Mapping) else None


def choose_noncombat_action(
    snapshot: Mapping[str, Any], actions: list[Mapping[str, Any]]
) -> Mapping[str, Any]:
    """Apply the smoke learner's fixed flow policy without inventing Host legality."""
    ordered = _ordered_actions(snapshot, actions)
    interaction = snapshot.get("interaction", {}).get("kind")
    preferred_roles = {
        # A reward alternative can remain visible after use. Taking a currently
        # advertised card gives this combat-only learner a bounded way out.
        "card_reward_selection": ("card", "option"),
        # Claim advertised rewards before using the screen-level Proceed
        # control. Potion disposal matters only when no reward is actionable.
        "reward_claim": ("reward", "potion"),
    }.get(interaction, ())
    for role in preferred_roles:
        candidates = [action for action in ordered if _subject_role(snapshot, action) == role]
        if candidates:
            return candidates[0]
    return ordered[0]


def run_episode(
    environment: Any,
    seed: str,
    model: LinearQ,
    rng: random.Random,
    *,
    train: bool,
    epsilon: float,
    max_actions: int,
    record_steps: bool = False,
    verify_successor: bool = False,
) -> dict[str, Any]:
    snapshot = environment.reset(seed)
    identity_after_reset = environment.episode_identity()
    total_reward = 0.0
    losses = []
    combat_decisions = 0
    delivered = 0
    inference_seconds = 0.0
    step_seconds = 0.0
    steps: list[dict[str, Any]] = []
    termination_reason = "action_limit"
    stale_refusals = 0
    successor_advances = 0
    supervision_attempts = 0
    while delivered < max_actions:
        supervision_attempts += 1
        if supervision_attempts > max_actions * 4 + 100:
            termination_reason = "supervision_limit"
            break
        if snapshot.get("interaction", {}).get("kind") == "game_over":
            termination_reason = "game_over"
            break
        actions = _ordered_actions(snapshot, action_list(snapshot))
        if not actions:
            termination_reason = "no_actions"
            break
        combat = snapshot.get("interaction", {}).get("kind") == "combat_turn"
        inference_started = time.perf_counter()
        selected = model.choose(snapshot, actions, rng, epsilon if train and combat else 0.0) \
            if combat else choose_noncombat_action(snapshot, actions)
        inference_seconds += time.perf_counter() - inference_started
        step_started = time.perf_counter()
        mutation_request_id = uuid4().hex
        receipt = environment.step(
            selected["bound_action_id"], snapshot["snapshot_id"], mutation_request_id
        )
        step_seconds += time.perf_counter() - step_started
        if receipt.get("delivery") != "delivered":
            retry = receipt.get("retry", {})
            fresh = receipt.get("successor")
            if (
                receipt.get("delivery") == "not_delivered"
                and receipt.get("reason_code") == "stale_snapshot"
                and retry.get("allowed") is True
                and isinstance(fresh, Mapping)
            ):
                stale_refusals += 1
                snapshot, advances = _observe_until_stable(environment, fresh)
                successor_advances += advances
                continue
            raise EpisodeExecutionError(
                f"Environment delivery failed: {receipt.get('delivery')}:{receipt.get('reason_code')}",
                {
                    "before": _snapshot_marker(snapshot),
                    "action": action_descriptor(snapshot, selected),
                    "mutation_request_id": mutation_request_id,
                    "receipt": receipt,
                },
            )
        if receipt.get("successor") is None:
            raise EpisodeExecutionError(
                "Delivered action did not include a successor observation.",
                {"before": _snapshot_marker(snapshot), "receipt": receipt},
            )
        if receipt.get("request_id") != mutation_request_id:
            raise EpisodeExecutionError(
                "Environment receipt request identity mismatch.",
                {"mutation_request_id": mutation_request_id, "receipt": receipt},
            )
        if receipt.get("action", {}).get("bound_action_id") != selected["bound_action_id"]:
            raise EpisodeExecutionError(
                "Environment receipt action identity mismatch.",
                {"selected": selected, "receipt": receipt},
            )
        successor = receipt["successor"]
        if successor.get("snapshot_id") == snapshot.get("snapshot_id"):
            raise EpisodeExecutionError(
                "Delivered action did not produce a distinct successor snapshot.",
                {
                    "before": _snapshot_marker(snapshot),
                    "action": action_descriptor(snapshot, selected),
                    "successor": _snapshot_marker(successor),
                },
            )
        if verify_successor:
            observed = environment.observe()
            if not _same_session(successor, observed):
                raise EpisodeExecutionError(
                    "Receipt successor and independent observation have different environment identity.",
                    {
                        "before": _snapshot_marker(snapshot),
                        "action": action_descriptor(snapshot, selected),
                        "available_actions": [
                            action_descriptor(snapshot, action) for action in actions
                        ],
                        "mutation_request_id": mutation_request_id,
                        "receipt_successor": _snapshot_marker(successor),
                        "independent_observation": _snapshot_marker(observed),
                    },
                )
            successor_sequence = int(successor.get("sequence", -1))
            observed_sequence = int(observed.get("sequence", -1))
            if observed_sequence < successor_sequence:
                raise EpisodeExecutionError(
                    "Independent observation moved backwards from the receipt successor.",
                    {
                        "receipt_successor": _snapshot_marker(successor),
                        "independent_observation": _snapshot_marker(observed),
                    },
                )
            if observed.get("snapshot_id") != successor.get("snapshot_id"):
                successor_advances += 1
                successor = observed
        successor, advances = _observe_until_stable(environment, successor)
        successor_advances += advances
        if record_steps:
            steps.append({
                "index": delivered,
                "before_snapshot_id": snapshot.get("snapshot_id"),
                "before_interaction_kind": snapshot.get("interaction", {}).get("kind"),
                "bound_action_id": selected.get("bound_action_id"),
                "action": action_descriptor(snapshot, selected),
                "available_actions": [
                    action_descriptor(snapshot, action) for action in actions
                ],
                "mutation_request_id": mutation_request_id,
                "delivery": receipt.get("delivery"),
                "successor_snapshot_id": successor.get("snapshot_id"),
                "successor_interaction_kind": successor.get("interaction", {}).get("kind"),
            })
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
    episode_identity = environment.episode_identity()
    return {
        "seed": seed,
        "terminal": snapshot.get("interaction", {}).get("kind"),
        "termination_reason": termination_reason,
        "victory": surface.get("victory") is True,
        "floor": persistent.get("run", {}).get("floor", 0),
        "hp": persistent.get("player", {}).get("hp", 0),
        "delivered": delivered,
        "stale_refusals": stale_refusals,
        "successor_advances": successor_advances,
        "supervision_attempts": supervision_attempts,
        "combat_decisions": combat_decisions,
        "shaped_return": total_reward,
        "mean_td_loss": sum(losses) / len(losses) if losses else None,
        "inference_seconds": inference_seconds,
        "step_seconds": step_seconds,
        "episode_identity": episode_identity,
        "identity_after_reset": identity_after_reset,
        "steps": steps if record_steps else None,
    }


def summarize(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "episodes": len(episodes),
        "terminal_episodes": sum(episode["terminal"] == "game_over" for episode in episodes),
        "victories": sum(episode["victory"] for episode in episodes),
        "mean_floor": sum(episode["floor"] for episode in episodes) / len(episodes),
        "mean_shaped_return": sum(episode["shaped_return"] for episode in episodes) / len(episodes),
        "delivered": sum(episode["delivered"] for episode in episodes),
        "stale_refusals": sum(episode.get("stale_refusals", 0) for episode in episodes),
        "successor_advances": sum(episode.get("successor_advances", 0) for episode in episodes),
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
    parser.add_argument("--learner-seed", type=int, default=731_2026)
    parser.add_argument("--training-seed-prefix", default="STPDTRAIN")
    parser.add_argument("--evaluation-seed-prefix", default="STPDEVAL")
    parser.add_argument("--output", default=".local/evidence/training-smoke/report.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    headless = Path(args.headless).resolve()
    candidate = Path(args.candidate).resolve()
    activate_headless_client(headless)
    from sts2_headless import ManagedPlayerEnvironment

    model = LinearQ()
    rng = random.Random(args.learner_seed)
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    with ManagedPlayerEnvironment(driver_command(headless, candidate)) as environment:
        provenance = environment.ready
        training_seeds = [
            derive_game_seed(args.training_seed_prefix, index + 1)
            for index in range(args.train_episodes)
        ]
        training = [
            run_episode(
                environment,
                seed,
                model,
                rng,
                train=True,
                epsilon=args.epsilon,
                max_actions=args.max_actions,
            )
            for seed in training_seeds
        ]
        evaluation_seeds = [
            derive_game_seed(args.evaluation_seed_prefix, index + 1)
            for index in range(args.eval_episodes)
        ]
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
        "learner_seed": args.learner_seed,
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
