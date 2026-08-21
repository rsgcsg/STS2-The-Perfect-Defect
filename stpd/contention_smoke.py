"""Fail-closed multi-seed, multi-environment actor/learner smoke.

The real entry point supplies ``sts2_headless.ThreadedVectorPlayerEnvironment``
and ``ManagedPlayerEnvironment``.  The runner itself only depends on their
small reset/step/close/ready surface, which keeps the acceptance criteria
unit-testable without starting a game candidate.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import threading
import time
from typing import Any, Callable, Mapping, Sequence

try:
    import resource
except ImportError:  # pragma: no cover - Windows has no resource module.
    resource = None

from .linear_q import LinearQ, combat_reward


REQUIRED_READY_FIELDS = (
    "headless",
    "candidate_build",
    "runtime_identity",
    "adapter_runtime_instance_id",
)


@dataclass(frozen=True)
class ContentionConfig:
    """Acceptance parameters for one multi-environment training smoke."""

    training_seeds: tuple[str, ...]
    workers: int = 2
    episodes_per_seed: int = 2
    max_actions: int = 600
    epsilon: float = 0.25

    def validate(self) -> None:
        if not self.training_seeds or len(set(self.training_seeds)) != len(self.training_seeds):
            raise ValueError("training_seeds must be non-empty and unique.")
        if self.workers < 2:
            raise ValueError("contention smoke requires at least two workers.")
        if self.episodes_per_seed < 1 or self.max_actions < 1:
            raise ValueError("episodes_per_seed and max_actions must be positive.")
        if not 0.0 <= self.epsilon <= 1.0:
            raise ValueError("epsilon must be between zero and one.")


def _episode_seed(training_seed: str, episode_index: int, worker_id: int) -> str:
    """Derive a stable game-valid seed without weakening Host validation."""

    material = f"{training_seed}\0{episode_index}\0{worker_id}".encode("utf-8")
    return f"STPD{hashlib.sha256(material).hexdigest()[:28].upper()}"


def source_identity(root: Path) -> dict[str, Any]:
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()
    return {"revision": revision, "worktree": "clean" if not status else "dirty"}


def action_list(snapshot: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    catalog = snapshot.get("bound_actions")
    if not isinstance(catalog, Mapping) or catalog.get("status") != "complete":
        raise RuntimeError("Snapshot does not contain a complete finite BoundAction projection.")
    actions = catalog.get("actions")
    if not isinstance(actions, list):
        raise RuntimeError("Snapshot BoundActions must be a list.")
    ids = [str(action.get("bound_action_id")) for action in actions]
    if any(identifier in {"None", ""} for identifier in ids):
        raise RuntimeError("Snapshot contains an unbound action.")
    if len(ids) != len(set(ids)):
        raise RuntimeError("Snapshot contains duplicate BoundAction identities.")
    return list(actions)


def _identity_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _shared_runtime_identity(value: Any) -> Any:
    """Return the immutable runtime build identity shared by isolated workers."""

    if not isinstance(value, Mapping):
        return value
    return {
        key: item
        for key, item in value.items()
        if key != "process_id"
    }


def validate_ready_identities(readies: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Validate exact runtime identity without pretending missing fields are safe."""

    missing = {
        str(index): [field for field in REQUIRED_READY_FIELDS if not ready.get(field)]
        for index, ready in enumerate(readies)
        if any(not ready.get(field) for field in REQUIRED_READY_FIELDS)
    }
    if missing:
        return {
            "status": "invalid",
            "missing_fields": missing,
            "consistent": False,
            "runtime_instances_unique": False,
        }
    comparable_fields = ("headless", "candidate_build")
    comparable = [
        tuple(
            [*(_identity_value(ready[field]) for field in comparable_fields),
             _identity_value(_shared_runtime_identity(ready["runtime_identity"]))]
        )
        for ready in readies
    ]
    instances = [str(ready["adapter_runtime_instance_id"]) for ready in readies]
    process_ids = [
        ready["runtime_identity"].get("process_id")
        for ready in readies
        if isinstance(ready["runtime_identity"], Mapping)
    ]
    consistent = len(set(comparable)) == 1
    unique_instances = len(instances) == len(set(instances))
    unique_processes = (
        not process_ids
        or (len(process_ids) == len(readies) and len(process_ids) == len(set(process_ids)))
    )
    return {
        "status": "valid" if consistent and unique_instances and unique_processes else "invalid",
        "missing_fields": {},
        "consistent": consistent,
        "runtime_instances_unique": unique_instances,
        "runtime_processes_unique": unique_processes,
        "workers": len(readies),
        "shared": {
            **{field: readies[0][field] for field in comparable_fields},
            "runtime_identity": _shared_runtime_identity(readies[0]["runtime_identity"]),
        },
        "runtime_instance_ids": instances,
        "runtime_process_ids": process_ids,
    }


class _LearnerContender:
    """A serialized learner shared by concurrently running actor updates."""

    def __init__(self, model: LinearQ):
        self.model = model
        self._lock = threading.Lock()
        self._contention_events = 0
        self._update_threads: set[int] = set()
        self._actor_ids: set[str] = set()
        self._updates = 0

    def update(
        self,
        actor_id: str,
        snapshot: Mapping[str, Any],
        action: Mapping[str, Any],
        reward: float,
        successor: Mapping[str, Any],
        successor_actions: list[Mapping[str, Any]],
    ) -> float:
        if not self._lock.acquire(blocking=False):
            self._contention_events += 1
            self._lock.acquire()
        try:
            self._actor_ids.add(actor_id)
            self._update_threads.add(threading.get_ident())
            self._updates += 1
            return self.model.update(snapshot, action, reward, successor, successor_actions)
        finally:
            self._lock.release()

    @property
    def metrics(self) -> dict[str, Any]:
        return {
            "learner_updates": self._updates,
            "learner_update_threads": len(self._update_threads),
            "actor_ids": sorted(self._actor_ids),
            "lock_contention_events": self._contention_events,
        }


def _episode_record(
    seed: str,
    worker_id: int,
    terminal: str,
    snapshot: Mapping[str, Any],
    delivered: int,
    combat_decisions: int,
    shaped_return: float,
    losses: list[float],
    environment: Any,
) -> dict[str, Any]:
    persistent = snapshot.get("persistent", {}).get("content", {})
    surface = snapshot.get("interaction", {}).get("content", {}).get("surface", {})
    episode_identity = environment.episode_identity()
    return {
        "seed": seed,
        "worker_id": worker_id,
        "terminal": terminal,
        "victory": surface.get("victory") is True,
        "floor": persistent.get("run", {}).get("floor", 0),
        "delivered": delivered,
        "combat_decisions": combat_decisions,
        "shaped_return": shaped_return,
        "mean_td_loss": sum(losses) / len(losses) if losses else None,
        "episode_identity": episode_identity,
    }


def run_contention_seed(
    environments: Sequence[Any],
    seed: str,
    model: LinearQ,
    config: ContentionConfig,
    vector_factory: Callable[[Sequence[Any]], Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    contender = _LearnerContender(model)
    episodes: list[dict[str, Any]] = []
    for episode_index in range(config.episodes_per_seed):
        seeds = [
            _episode_seed(seed, episode_index, worker_id)
            for worker_id in range(config.workers)
        ]
        vector = vector_factory(environments)
        snapshots = list(vector.reset(seeds))
        active = set(range(config.workers))
        delivered = [0] * config.workers
        combat_decisions = [0] * config.workers
        shaped_returns = [0.0] * config.workers
        action_counts = [0] * config.workers
        losses: list[list[float]] = [[] for _ in environments]
        while active:
            selected: dict[int, Mapping[str, Any]] = {}
            action_inputs: list[tuple[str, str]] = []
            active_ids = sorted(active)
            for worker_id in active_ids:
                snapshot = snapshots[worker_id]
                if action_counts[worker_id] >= config.max_actions:
                    episodes.append(_episode_record(
                        seeds[worker_id], worker_id, "action_limit", snapshot, delivered[worker_id],
                        combat_decisions[worker_id], shaped_returns[worker_id], losses[worker_id],
                        environments[worker_id],
                    ))
                    active.remove(worker_id)
                    continue
                if snapshot.get("interaction", {}).get("kind") == "game_over":
                    episodes.append(_episode_record(
                        seeds[worker_id], worker_id, "game_over", snapshot, delivered[worker_id],
                        combat_decisions[worker_id], shaped_returns[worker_id], losses[worker_id],
                        environments[worker_id],
                    ))
                    active.remove(worker_id)
                    continue
                actions = action_list(snapshot)
                if not actions:
                    episodes.append(_episode_record(
                        seeds[worker_id], worker_id, "no_action", snapshot, delivered[worker_id],
                        combat_decisions[worker_id], shaped_returns[worker_id], losses[worker_id],
                        environments[worker_id],
                    ))
                    active.remove(worker_id)
                    continue
                combat = snapshot.get("interaction", {}).get("kind") == "combat_turn"
                selected_action = model.choose(
                    snapshot,
                    actions,
                    random.Random(f"{seed}:{episode_index}:{worker_id}:{delivered[worker_id]}"),
                    config.epsilon if combat else 0.0,
                ) if combat else actions[0]
                selected[worker_id] = selected_action
                action_inputs.append((str(selected_action["bound_action_id"]), str(snapshot["snapshot_id"])))
            if not action_inputs:
                continue
            live_ids = [worker_id for worker_id in active_ids if worker_id in selected]
            live_vector = vector_factory([environments[worker_id] for worker_id in live_ids])
            receipts = live_vector.step(action_inputs)
            update_jobs = []
            for worker_id, receipt in zip(live_ids, receipts):
                if receipt.get("delivery") != "delivered" or receipt.get("successor") is None:
                    raise RuntimeError(
                        f"worker {worker_id} delivery failed: "
                        f"{receipt.get('delivery')}:{receipt.get('reason_code')}"
                    )
                before = snapshots[worker_id]
                successor = receipt["successor"]
                snapshots[worker_id] = successor
                delivered[worker_id] += 1
                action_counts[worker_id] += 1
                combat = before.get("interaction", {}).get("kind") == "combat_turn"
                if not combat:
                    continue
                combat_decisions[worker_id] += 1
                reward = combat_reward(before, successor)
                shaped_returns[worker_id] += reward
                next_actions = []
                if successor.get("interaction", {}).get("kind") == "combat_turn":
                    next_actions = action_list(successor)
                update_jobs.append((
                    f"{seed}:{episode_index}:{worker_id}",
                    before,
                    selected[worker_id],
                    reward,
                    successor,
                    next_actions,
                    worker_id,
                ))
            with ThreadPoolExecutor(max_workers=max(1, len(update_jobs))) as executor:
                futures = [executor.submit(contender.update, *job[:-1]) for job in update_jobs]
                for future, job in zip(futures, update_jobs):
                    losses[job[-1]].append(future.result())
            for worker_id in list(active):
                if snapshots[worker_id].get("interaction", {}).get("kind") == "game_over":
                    episodes.append(_episode_record(
                        seeds[worker_id], worker_id, "game_over", snapshots[worker_id], delivered[worker_id],
                        combat_decisions[worker_id], shaped_returns[worker_id], losses[worker_id],
                        environments[worker_id],
                    ))
                    active.remove(worker_id)
    return episodes, contender.metrics


def _summary(episodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not episodes:
        return {
            "episodes": 0,
            "terminal_episodes": 0,
            "unknown_or_failed": 0,
            "delivered": 0,
            "combat_decisions": 0,
            "mean_floor": None,
            "mean_shaped_return": None,
        }
    return {
        "episodes": len(episodes),
        "terminal_episodes": sum(item["terminal"] == "game_over" for item in episodes),
        "unknown_or_failed": sum(item["terminal"] != "game_over" for item in episodes),
        "delivered": sum(item["delivered"] for item in episodes),
        "combat_decisions": sum(item["combat_decisions"] for item in episodes),
        "mean_floor": sum(item["floor"] for item in episodes) / len(episodes),
        "mean_shaped_return": sum(item["shaped_return"] for item in episodes) / len(episodes),
    }


def contention_verdict(
    reports: Sequence[Mapping[str, Any]],
    config: ContentionConfig,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a strict verdict; missing evidence never becomes a pass."""

    expected = len(config.training_seeds) * config.workers * config.episodes_per_seed
    all_episodes = [episode for report in reports for episode in report.get("episodes", [])]
    summaries = [_summary(report.get("episodes", [])) for report in reports]
    updates = sum(report.get("contention", {}).get("learner_updates", 0) for report in reports)
    delivered = sum(item.get("delivered", 0) for item in all_episodes)
    checks = {
        "seed_coverage": len(reports) == len(config.training_seeds)
        and {report.get("seed") for report in reports} == set(config.training_seeds),
        "worker_coverage": len(all_episodes) == expected
        and all(sum(item.get("worker_id") == worker for item in report.get("episodes", [])) == config.episodes_per_seed
                for report in reports for worker in range(config.workers)),
        "terminal_complete": bool(all_episodes) and all(item.get("terminal") == "game_over" for item in all_episodes),
        "no_unknown_or_failed": all(item.get("terminal") == "game_over" for item in all_episodes),
        "learner_update_parity": updates == sum(item.get("combat_decisions", 0) for item in all_episodes),
        "identity_valid": identity.get("status") == "valid",
        "multi_actor": config.workers >= 2 and len(all_episodes) >= config.workers,
        "updates_from_all_workers": len({
            actor_id
            for report in reports
            for actor_id in report.get("contention", {}).get("actor_ids", [])
        }) >= config.workers,
        "samples_present": delivered > 0,
        "episode_provenance": bool(all_episodes) and all(
            item.get("episode_identity", {}).get("episode_provenance", {}).get("verdict")
            == "provenance_pass"
            for item in all_episodes
        ),
    }
    learning_criteria = {
        "all_seeds_have_samples": all(summary["delivered"] > 0 for summary in summaries),
        "all_seeds_terminal_complete": all(
            summary["episodes"] > 0 and summary["terminal_episodes"] == summary["episodes"]
            for summary in summaries
        ),
        "all_seed_updates_match_combat_decisions": checks["learner_update_parity"],
        "sample_discarded": False,
    }
    checks["learning_criteria"] = (
        learning_criteria["all_seeds_have_samples"]
        and learning_criteria["all_seeds_terminal_complete"]
        and learning_criteria["all_seed_updates_match_combat_decisions"]
        and not learning_criteria["sample_discarded"]
    )
    return {
        "status": "contention_smoke_pass" if all(checks.values()) else "contention_smoke_failed",
        "checks": checks,
        "expected_episodes": expected,
        "actual_episodes": len(all_episodes),
        "delivered": delivered,
        "learner_updates": updates,
        "per_seed": summaries,
        "learning_criteria": learning_criteria,
    }


def _resource_snapshot() -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_SELF) if resource is not None else None
    return {
        "platform": platform.platform(),
        "logical_cpus": os.cpu_count(),
        "max_rss": usage.ru_maxrss if usage is not None else None,
        "max_rss_unit": "bytes" if platform.system() == "Darwin" else "kib" if usage is not None else None,
        "python_cpu_seconds": time.process_time(),
    }


def _resource_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    before_cpu = before.get("python_cpu_seconds")
    after_cpu = after.get("python_cpu_seconds")
    before_rss = before.get("max_rss")
    after_rss = after.get("max_rss")
    return {
        "python_cpu_seconds": after_cpu - before_cpu if before_cpu is not None and after_cpu is not None else None,
        "max_rss": after_rss - before_rss if before_rss is not None and after_rss is not None else None,
        "max_rss_unit": after.get("max_rss_unit"),
    }


def write_report(output: Path, report: Mapping[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def run_contention(
    env_factory: Callable[[int], Any],
    config: ContentionConfig,
    *,
    vector_factory: Callable[[Sequence[Any]], Any],
    model_factory: Callable[[], LinearQ] = LinearQ,
) -> dict[str, Any]:
    config.validate()
    started = time.perf_counter()
    resource_before = _resource_snapshot()
    environments: list[Any] = []
    identity: dict[str, Any] = {
        "status": "invalid",
        "missing_fields": {"environment": list(REQUIRED_READY_FIELDS)},
        "consistent": False,
        "runtime_instances_unique": False,
    }
    reports: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        for worker_id in range(config.workers):
            environments.append(env_factory(worker_id))
        readies = [getattr(environment, "ready", {}) for environment in environments]
        identity = validate_ready_identities(readies)
        if identity.get("status") != "valid":
            errors.append("runtime identity is incomplete or inconsistent")
        else:
            for seed in config.training_seeds:
                model = model_factory()
                episodes, contention = run_contention_seed(
                    environments, seed, model, config, vector_factory
                )
                reports.append({
                    "seed": seed,
                    "episodes": episodes,
                    "summary": _summary(episodes),
                    "contention": contention,
                    "model": model.to_dict(),
                })
    except Exception as error:
        errors.append(f"{type(error).__name__}: {error}")
    finally:
        for environment in environments:
            try:
                environment.close()
            except Exception as error:
                errors.append(f"close {type(error).__name__}: {error}")
    verdict = contention_verdict(reports, config, identity)
    wall_seconds = time.perf_counter() - started
    report = {
        "schema": "stpd/multi-seed-contention-smoke-1",
        "status": "contention_smoke_failed" if errors else verdict["status"],
        "stpd": None,
        "runtime_identity": identity,
        "configuration": {
            "training_seeds": list(config.training_seeds),
            "workers": config.workers,
            "episodes_per_seed": config.episodes_per_seed,
            "max_actions": config.max_actions,
            "epsilon": config.epsilon,
        },
        "seeds": reports,
        "verdict": verdict,
        "errors": errors,
        "pipeline": {
            "topology": "threaded_vector_multi_actor_shared_learner",
            "actor_workers": config.workers,
            "learner_threads": sum(
                item.get("contention", {}).get("learner_update_threads", 0)
                for item in reports
            ),
            "wall_seconds": wall_seconds,
            "usable_samples": verdict["delivered"],
            "usable_samples_per_second": verdict["delivered"] / wall_seconds if wall_seconds > 0 else None,
            "learner_updates_per_second": verdict["learner_updates"] / wall_seconds if wall_seconds > 0 else None,
            "policy_version_lag": 0,
            "queue_depth": 0,
            "trajectory_age_seconds": 0.0,
            "discarded_samples": 0 if not errors else None,
        },
        "resource_envelope": {
            "before": resource_before,
            "after": _resource_snapshot(),
            "workers": config.workers,
        },
        "non_claims": [
            "This is a contention and integration smoke, not a training-quality or policy-transfer result.",
            "It does not prove Reference-host parity, long-run reliability, or H1 admission.",
            "No Headless/Connector semantic code is owned or modified by STPD.",
        ],
    }
    report["resource_envelope"]["delta"] = _resource_delta(
        report["resource_envelope"]["before"], report["resource_envelope"]["after"]
    )
    return report


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Fail-closed multi-seed actor/learner contention smoke.")
    parser.add_argument("--headless", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--training-seed", action="append", dest="training_seeds")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--episodes-per-seed", type=int, default=2)
    parser.add_argument("--max-actions", type=int, default=600)
    parser.add_argument("--epsilon", type=float, default=0.25)
    parser.add_argument("--output", default=".local/evidence/contention-smoke/report.json")
    args = parser.parse_args()
    from sts2_headless import ManagedPlayerEnvironment, ThreadedVectorPlayerEnvironment

    root = Path(__file__).resolve().parents[1]
    headless = Path(args.headless).resolve()
    candidate = Path(args.candidate).resolve()
    seeds = tuple(args.training_seeds or ("STPDCONTEND01", "STPDCONTEND02", "STPDCONTEND03"))
    config = ContentionConfig(
        training_seeds=seeds,
        workers=args.workers,
        episodes_per_seed=args.episodes_per_seed,
        max_actions=args.max_actions,
        epsilon=args.epsilon,
    )
    command = ["node", str(headless / "tools" / "managed-pe-driver.mjs"), "--candidate", str(candidate)]

    def env_factory(_: int) -> Any:
        return ManagedPlayerEnvironment(command)

    report = run_contention(
        env_factory,
        config,
        vector_factory=ThreadedVectorPlayerEnvironment,
    )
    report["stpd"] = source_identity(root)
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    write_report(output, report)
    print(json.dumps({
        "status": report["status"],
        "report_file": str(output),
        "verdict": report["verdict"],
        "pipeline": report["pipeline"],
    }, indent=2))
    if report["status"] != "contention_smoke_pass":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
