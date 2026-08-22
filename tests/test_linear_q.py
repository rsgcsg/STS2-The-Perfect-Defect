import random
import unittest
from concurrent.futures import ThreadPoolExecutor

from stpd.contention_smoke import (
    ContentionConfig,
    _episode_seed,
    contention_verdict,
    run_contention,
    validate_ready_identities,
)
from stpd.game_seed import derive_game_seed, require_canonical_game_seed
from stpd.linear_q import LinearQ, combat_reward, features
from stpd.multi_seed_learning import multi_seed_verdict
from stpd.reference_transfer import transfer_verdict
from stpd.training_smoke import (
    action_list,
    action_policy_descriptor,
    choose_noncombat_action,
    learning_verdict,
    run_episode,
)


def snapshot(enemy_hp=20, player_hp=30, kind="combat_turn", victory=False):
    return {
        "snapshot_id": "s",
        "persistent": {"content": {"player": {"hp": player_hp, "max_hp": 40}, "run": {"floor": 1}}},
        "interaction": {
            "kind": kind,
            "content": {
                "context": {
                    "player": {"energy": 3},
                    "enemies": [
                        {"hp": enemy_hp, "block": 0, "intents": [{"type": "Attack", "label": "6"}]}
                    ],
                },
                "surface": {"victory": victory},
            },
        },
        "referents": [
            {"referent_id": "card", "properties": {"definition_id": "STRIKE", "type": "Attack"}}
        ],
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


class StaleThenTerminalEnvironment(FakeEnvironment):
    def step(self, action_id, snapshot_id, request_id):
        return {
            "delivery": "not_delivered",
            "reason_code": "stale_snapshot",
            "retry": {"allowed": True},
            "successor": {
                "snapshot_id": "settling",
                "sequence": 2,
                "status": "settling",
                "session": {
                    "runtime_instance_id": "runtime",
                    "environment_fingerprint": "environment",
                },
                "interaction": {"kind": "event_option"},
                "bound_actions": {"status": "complete", "actions": []},
            },
        }

    def observe(self):
        return {
            "snapshot_id": "terminal",
            "sequence": 3,
            "status": "observed",
            "session": {"runtime_instance_id": "runtime", "environment_fingerprint": "environment"},
            "persistent": {"content": {"player": {"hp": 10}, "run": {"floor": 2}}},
            "interaction": {"kind": "game_over", "content": {"surface": {"victory": False}}},
            "bound_actions": {"status": "complete", "actions": []},
        }


class FakeVector:
    def __init__(self, environments):
        self.environments = tuple(environments)

    def reset(self, seeds):
        with ThreadPoolExecutor(max_workers=len(self.environments)) as executor:
            return tuple(
                executor.map(
                    lambda pair: pair[0].reset(pair[1]),
                    zip(self.environments, seeds, strict=True),
                )
            )

    def step(self, actions):
        with ThreadPoolExecutor(max_workers=len(self.environments)) as executor:
            return tuple(
                executor.map(
                    lambda pair: pair[0].step(*pair[1]),
                    zip(self.environments, actions, strict=True),
                )
            )


class LinearQTest(unittest.TestCase):
    def test_episode_seed_is_stable_unique_and_game_valid(self):
        first = _episode_seed("training-seed with punctuation", 0, 0)
        self.assertEqual(first, _episode_seed("training-seed with punctuation", 0, 0))
        self.assertNotEqual(first, _episode_seed("training-seed with punctuation", 0, 1))
        self.assertTrue(first.isascii())
        self.assertTrue(first.isalnum())
        self.assertLessEqual(len(first), 64)

    def test_experiment_seed_is_preserved_by_the_native_seed_alphabet(self):
        first = derive_game_seed("training label", 1)
        self.assertEqual(first, derive_game_seed("training label", 1))
        self.assertNotEqual(first, derive_game_seed("training label", 2))
        self.assertEqual(require_canonical_game_seed(first), first)
        with self.assertRaises(ValueError):
            require_canonical_game_seed("contains-I-or-O")

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

    def test_frozen_policy_round_trip(self):
        model = LinearQ(alpha=0.1, gamma=0.8)
        model.weights = {"bias": 1.25, "verb:play": -0.5}
        model.updates = 17
        restored = LinearQ.from_dict(model.to_dict())
        self.assertEqual(restored.to_dict(), model.to_dict())
        with self.assertRaises(ValueError):
            LinearQ.from_dict({"algorithm": "other", "weights": {}})

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

    def test_multi_seed_learning_requires_every_trial_and_provenance(self):
        trial = {
            "verdict": {"status": "learning_smoke_pass", "terminal_complete": True},
            "provenance_pass": True,
        }
        self.assertEqual(
            multi_seed_verdict([trial, trial])["status"],
            "multi_seed_learning_pass",
        )
        self.assertEqual(
            multi_seed_verdict([trial, {**trial, "provenance_pass": False}])["status"],
            "multi_seed_learning_failed",
        )

    def test_reference_transfer_separates_execution_from_exact_outcome_parity(self):
        identity = {"episode_provenance": {"verdict": "provenance_pass"}}
        candidate = [
            {
                "seed": "SEED1",
                "terminal": "game_over",
                "victory": False,
                "floor": 5,
                "hp": 0,
                "delivered": 10,
                "episode_identity": identity,
            }
        ]
        reference = [{**candidate[0], "floor": 6}]
        verdict = transfer_verdict(candidate, reference)
        self.assertEqual(verdict["status"], "reference_transfer_execution_pass")
        self.assertFalse(verdict["exact_terminal_outcomes_match"])
        self.assertEqual(verdict["semantic_parity_claim"], "not_claimed")
        self.assertEqual(
            transfer_verdict(candidate, [{**reference[0], "terminal": "combat_turn"}])["status"],
            "reference_transfer_failed",
        )

    def test_action_list_rejects_incomplete_or_duplicate_projection(self):
        with self.assertRaises(RuntimeError):
            action_list({"bound_actions": {"status": "partial", "actions": []}})
        with self.assertRaises(RuntimeError):
            action_list(
                {
                    "bound_actions": {
                        "status": "complete",
                        "actions": [{"bound_action_id": "same"}, {"bound_action_id": "same"}],
                    }
                }
            )

    def test_noncombat_policy_uses_interaction_and_referent_roles_not_labels(self):
        card_reward = {
            "interaction": {"kind": "card_reward_selection"},
            "referents": [
                {"referent_id": "skip", "role": "option", "label": "跳过"},
                {"referent_id": "card", "role": "card", "label": "打击"},
            ],
        }
        skip = {
            "bound_action_id": "skip-action",
            "verb": "activate",
            "subject_referent_id": "skip",
            "label": "跳过",
            "arguments": [],
        }
        take = {
            "bound_action_id": "take-action",
            "verb": "activate",
            "subject_referent_id": "card",
            "label": "Take Strike",
            "arguments": [],
        }
        self.assertEqual(
            choose_noncombat_action(card_reward, [skip, take])["bound_action_id"],
            "take-action",
        )

        reward_claim = {
            "interaction": {"kind": "reward_claim"},
            "referents": [{"referent_id": "reward", "role": "reward", "label": "奖励"}],
        }
        proceed = {
            "bound_action_id": "proceed",
            "verb": "activate",
            "subject_referent_id": None,
            "label": "Proceed",
            "arguments": [],
        }
        claim = {
            "bound_action_id": "claim",
            "verb": "activate",
            "subject_referent_id": "reward",
            "label": "领取",
            "arguments": [],
        }
        self.assertEqual(
            choose_noncombat_action(reward_claim, [proceed, claim])["bound_action_id"],
            "claim",
        )

    def test_policy_ordering_excludes_localized_presentation_text(self):
        action = {
            "bound_action_id": "take",
            "verb": "select",
            "label": "Take Strike",
            "subject_referent_id": "card",
            "arguments": [],
        }
        english = {
            "referents": [
                {
                    "referent_id": "card",
                    "role": "card",
                    "kind": "entity",
                    "label": "Strike",
                    "properties": {
                        "definition_id": "STRIKE",
                        "name": "Strike",
                        "type": "Attack",
                        "cost": "1",
                    },
                }
            ]
        }
        localized = {
            "referents": [
                {
                    "referent_id": "card",
                    "role": "card",
                    "kind": "entity",
                    "label": "打击",
                    "properties": {
                        "definition_id": "STRIKE",
                        "name": "打击",
                        "type": "Attack",
                        "cost": "1",
                    },
                }
            ]
        }
        self.assertEqual(
            action_policy_descriptor(english, action),
            action_policy_descriptor(localized, {**action, "label": "选择打击"}),
        )

    def test_episode_supervision_recovers_stale_without_retrying_the_old_action(self):
        environment = StaleThenTerminalEnvironment(0)
        initial = environment.reset("seed")
        initial.update(
            {
                "sequence": 1,
                "status": "interactive",
                "session": {
                    "runtime_instance_id": "runtime",
                    "environment_fingerprint": "environment",
                },
            }
        )
        episode = run_episode(
            environment,
            "seed",
            LinearQ(),
            random.Random(1),
            train=False,
            epsilon=0.0,
            max_actions=2,
            verify_successor=True,
        )
        self.assertEqual(episode["termination_reason"], "game_over")
        self.assertEqual(episode["delivered"], 0)
        self.assertEqual(episode["stale_refusals"], 1)
        self.assertEqual(episode["successor_advances"], 1)

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
        self.assertEqual(
            validate_ready_identities([{**ready[0], "runtime_identity": "other"}, ready[1]])[
                "status"
            ],
            "invalid",
        )
        self.assertEqual(
            validate_ready_identities(
                [{**ready[0], "adapter_runtime_instance_id": "instance-2"}, ready[1]]
            )["status"],
            "invalid",
        )

    def test_runtime_identity_separates_shared_build_from_worker_process(self):
        runtime = {
            "type": "runtime_identity",
            "host_assembly_sha256": "host-sha",
            "host_module_mvid": "host-mvid",
            "sts2_assembly_sha256": "game-sha",
            "sts2_module_mvid": "game-mvid",
        }
        ready = [
            {
                "headless": "headless-a",
                "candidate_build": "candidate-a",
                "runtime_identity": {**runtime, "process_id": 101},
                "adapter_runtime_instance_id": "instance-1",
            },
            {
                "headless": "headless-a",
                "candidate_build": "candidate-a",
                "runtime_identity": {**runtime, "process_id": 102},
                "adapter_runtime_instance_id": "instance-2",
            },
        ]
        identity = validate_ready_identities(ready)
        self.assertEqual(identity["status"], "valid")
        self.assertTrue(identity["runtime_processes_unique"])
        self.assertEqual(identity["runtime_process_ids"], [101, 102])
        self.assertNotIn("process_id", identity["shared"]["runtime_identity"])
        self.assertEqual(
            validate_ready_identities(
                [
                    ready[0],
                    {**ready[1], "runtime_identity": {**runtime, "process_id": 101}},
                ]
            )["status"],
            "invalid",
        )
        self.assertEqual(
            validate_ready_identities(
                [
                    ready[0],
                    {
                        **ready[1],
                        "runtime_identity": {
                            **runtime,
                            "host_assembly_sha256": "other",
                            "process_id": 102,
                        },
                    },
                ]
            )["status"],
            "invalid",
        )

    def test_contention_verdict_fails_closed_on_missing_seed_worker_or_terminal(self):
        config = ContentionConfig(("seed-a", "seed-b"), workers=2, episodes_per_seed=1)
        identity = {"status": "valid"}
        complete = [
            {
                "seed": seed,
                "episodes": [
                    {
                        "worker_id": 0,
                        "terminal": "game_over",
                        "delivered": 2,
                        "combat_decisions": 1,
                        "floor": 1,
                        "shaped_return": 0,
                        "episode_identity": {"episode_provenance": {"verdict": "provenance_pass"}},
                    },
                    {
                        "worker_id": 1,
                        "terminal": "game_over",
                        "delivered": 2,
                        "combat_decisions": 1,
                        "floor": 1,
                        "shaped_return": 0,
                        "episode_identity": {"episode_provenance": {"verdict": "provenance_pass"}},
                    },
                ],
                "contention": {"learner_updates": 2, "actor_ids": [f"{seed}:0:0", f"{seed}:0:1"]},
            }
            for seed in config.training_seeds
        ]
        verdict = contention_verdict(complete, config, identity)
        self.assertEqual(verdict["status"], "contention_smoke_pass")
        self.assertTrue(verdict["learning_criteria"]["all_seeds_have_samples"])
        self.assertTrue(verdict["learning_criteria"]["all_seed_updates_match_combat_decisions"])
        self.assertEqual(
            contention_verdict(complete[:-1], config, identity)["status"],
            "contention_smoke_failed",
        )
        incomplete = [
            dict(
                complete[0],
                episodes=[
                    dict(complete[0]["episodes"][0], terminal="action_limit"),
                    complete[0]["episodes"][1],
                ],
            ),
            complete[1],
        ]
        self.assertEqual(
            contention_verdict(incomplete, config, identity)["status"], "contention_smoke_failed"
        )

    def test_contention_runner_uses_multiple_fake_actors_without_runtime(self):
        config = ContentionConfig(
            ("seed-a", "seed-b"), workers=2, episodes_per_seed=1, max_actions=2
        )
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
