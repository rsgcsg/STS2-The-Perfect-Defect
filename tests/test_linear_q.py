import random
from concurrent.futures import ThreadPoolExecutor
import unittest

from stpd.linear_q import LinearQ, combat_reward, features
from stpd.contention_smoke import (
    ContentionConfig,
    contention_verdict,
    run_contention,
    validate_ready_identities,
)
from stpd.training_smoke import action_list, learning_verdict


def snapshot(enemy_hp=20, player_hp=30, kind="combat_turn", victory=False):
    return {
        "snapshot_id": "s",
        "persistent": {"content": {"player": {"hp": player_hp, "max_hp": 40}, "run": {"floor": 1}}},
        "interaction": {
            "kind": kind,
            "content": {
                "context": {
                    "player": {"energy": 3},
                    "enemies": [{"hp": enemy_hp, "block": 0, "intents": [{"type": "Attack", "label": "6"}]}],
                },
                "surface": {"victory": victory},
            },
        },
        "referents": [{"referent_id": "card", "properties": {"definition_id": "STRIKE", "type": "Attack"}}],
    }


ACTION = {"bound_action_id": "a", "verb": "play", "subject_referent_id": "card"}


class FakeEnvironment:
    def __init__(self, worker_id):
        self.worker_id = worker_id
        self.ready = {
            "headless": "fake-headless",
            "candidate_build": "fake-candidate",
            "runtime_identity": "fake-runtime",
            "adapter_runtime_instance_id": f"fake-instance-{worker_id}",
        }
        self._snapshot = None
        self._seed = None

    def reset(self, seed):
        self._seed = seed
        self._snapshot = {
            "snapshot_id": f"{seed}:snapshot",
            "persistent": {"content": {"player": {"hp": 30}, "run": {"floor": 1}}},
            "interaction": {
                "kind": "combat_turn",
                "content": {"context": {"player": {"energy": 3}, "enemies": []}},
            },
            "bound_actions": {"status": "complete", "actions": [ACTION]},
        }
        return self._snapshot

    def step(self, action_id, snapshot_id):
        assert self._snapshot["snapshot_id"] == snapshot_id
        assert action_id == ACTION["bound_action_id"]
        self._snapshot = {
            "snapshot_id": f"{snapshot_id}:successor",
            "persistent": {"content": {"player": {"hp": 30}, "run": {"floor": 2}}},
            "interaction": {
                "kind": "game_over",
                "content": {"surface": {"victory": False}},
            },
        }
        return {"delivery": "delivered", "successor": self._snapshot}

    def episode_identity(self):
        return {
            "adapter_runtime_instance_id": self.ready["adapter_runtime_instance_id"],
            "episode_provenance": {
                "verdict": "provenance_pass",
                "requested_seed": self._seed,
                "actual_seed": self._seed,
            },
        }

    def close(self):
        return None


class NonTerminalFakeEnvironment(FakeEnvironment):
    def step(self, action_id, snapshot_id):
        assert self._snapshot["snapshot_id"] == snapshot_id
        self._snapshot = {
            "snapshot_id": f"{snapshot_id}:successor",
            "persistent": {"content": {"player": {"hp": 30}, "run": {"floor": 1}}},
            "interaction": {
                "kind": "combat_turn",
                "content": {"context": {"player": {"energy": 3}, "enemies": []}},
            },
            "bound_actions": {"status": "complete", "actions": [ACTION]},
        }
        return {"delivery": "delivered", "successor": self._snapshot}


class FakeVector:
    def __init__(self, environments):
        self.environments = tuple(environments)

    def reset(self, seeds):
        with ThreadPoolExecutor(max_workers=len(self.environments)) as executor:
            return tuple(executor.map(lambda pair: pair[0].reset(pair[1]), zip(self.environments, seeds)))

    def step(self, actions):
        with ThreadPoolExecutor(max_workers=len(self.environments)) as executor:
            return tuple(executor.map(lambda pair: pair[0].step(*pair[1]), zip(self.environments, actions)))


class LinearQTest(unittest.TestCase):
    def test_reward_uses_only_visible_successor_facts(self):
        self.assertGreater(combat_reward(snapshot(), snapshot(enemy_hp=10)), 0)
        self.assertLess(combat_reward(snapshot(), snapshot(player_hp=20)), 0)

    def test_update_changes_action_score(self):
        model = LinearQ(alpha=0.1)
        before = model.score(snapshot(), ACTION)
        model.update(snapshot(), ACTION, 1.0, snapshot(enemy_hp=10), [])
        self.assertGreater(model.score(snapshot(), ACTION), before)
        self.assertIn("verb:play", features(snapshot(), ACTION))
        self.assertEqual(model.choose(snapshot(), [ACTION], random.Random(1), 0), ACTION)

    def test_learning_verdict_fails_closed_on_regression_or_incomplete_terminal(self):
        baseline = {
            "episodes": 4,
            "terminal_episodes": 4,
            "mean_floor": 3.0,
            "mean_shaped_return": 1.0,
        }
        passing = {
            "episodes": 4,
            "terminal_episodes": 4,
            "mean_floor": 4.0,
            "mean_shaped_return": 2.0,
        }
        self.assertEqual(learning_verdict(baseline, passing)["status"], "learning_smoke_pass")
        self.assertEqual(
            learning_verdict(baseline, {**passing, "mean_floor": 2.0})["status"],
            "learning_smoke_failed",
        )
        self.assertEqual(
            learning_verdict(baseline, {**passing, "terminal_episodes": 3})["status"],
            "learning_smoke_failed",
        )

    def test_action_list_rejects_incomplete_or_duplicate_projection(self):
        with self.assertRaises(RuntimeError):
            action_list({"bound_actions": {"status": "partial", "actions": []}})
        with self.assertRaises(RuntimeError):
            action_list({"bound_actions": {
                "status": "complete",
                "actions": [{"bound_action_id": "same"}, {"bound_action_id": "same"}],
            }})

    def test_runtime_identity_requires_shared_game_and_unique_instances(self):
        ready = [
            {
                "headless": "headless-a",
                "candidate_build": "candidate-a",
                "runtime_identity": "runtime-a",
                "adapter_runtime_instance_id": "instance-1",
            },
            {
                "headless": "headless-a",
                "candidate_build": "candidate-a",
                "runtime_identity": "runtime-a",
                "adapter_runtime_instance_id": "instance-2",
            },
        ]
        self.assertEqual(validate_ready_identities(ready)["status"], "valid")
        self.assertEqual(validate_ready_identities([{**ready[0], "runtime_identity": "other"}, ready[1]])["status"], "invalid")
        self.assertEqual(validate_ready_identities([{**ready[0], "adapter_runtime_instance_id": "instance-2"}, ready[1]])["status"], "invalid")

    def test_contention_verdict_fails_closed_on_missing_seed_worker_or_terminal(self):
        config = ContentionConfig(("seed-a", "seed-b"), workers=2, episodes_per_seed=1)
        identity = {"status": "valid"}
        complete = [{
            "seed": seed,
            "episodes": [
                {"worker_id": 0, "terminal": "game_over", "delivered": 2, "combat_decisions": 1, "floor": 1, "shaped_return": 0, "episode_identity": {"episode_provenance": {"verdict": "provenance_pass"}}},
                {"worker_id": 1, "terminal": "game_over", "delivered": 2, "combat_decisions": 1, "floor": 1, "shaped_return": 0, "episode_identity": {"episode_provenance": {"verdict": "provenance_pass"}}},
            ],
            "contention": {"learner_updates": 2, "actor_ids": [f"{seed}:0:0", f"{seed}:0:1"]},
        } for seed in config.training_seeds]
        verdict = contention_verdict(complete, config, identity)
        self.assertEqual(verdict["status"], "contention_smoke_pass")
        self.assertTrue(verdict["learning_criteria"]["all_seeds_have_samples"])
        self.assertTrue(verdict["learning_criteria"]["all_seed_updates_match_combat_decisions"])
        self.assertEqual(
            contention_verdict(complete[:-1], config, identity)["status"],
            "contention_smoke_failed",
        )
        incomplete = [dict(complete[0], episodes=[dict(complete[0]["episodes"][0], terminal="action_limit"), complete[0]["episodes"][1]]), complete[1]]
        self.assertEqual(contention_verdict(incomplete, config, identity)["status"], "contention_smoke_failed")

    def test_contention_runner_uses_multiple_fake_actors_without_runtime(self):
        config = ContentionConfig(("seed-a", "seed-b"), workers=2, episodes_per_seed=1, max_actions=2)
        report = run_contention(
            FakeEnvironment,
            config,
            vector_factory=FakeVector,
        )
        self.assertEqual(report["status"], "contention_smoke_pass")
        self.assertEqual(report["verdict"]["actual_episodes"], 4)
        self.assertEqual(report["verdict"]["learner_updates"], 4)
        self.assertEqual(report["pipeline"]["actor_workers"], 2)
        self.assertFalse(report["errors"])

    def test_contention_runner_stops_and_fails_on_action_limit(self):
        report = run_contention(
            NonTerminalFakeEnvironment,
            ContentionConfig(("seed-a",), workers=2, episodes_per_seed=1, max_actions=1),
            vector_factory=FakeVector,
        )
        self.assertEqual(report["status"], "contention_smoke_failed")
        self.assertEqual(report["verdict"]["checks"]["terminal_complete"], False)
        self.assertEqual(report["seeds"][0]["episodes"][0]["terminal"], "action_limit")


if __name__ == "__main__":
    unittest.main()
