import random
import unittest

from stpd.linear_q import LinearQ, combat_reward, features
from stpd.training_smoke import learning_verdict


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


if __name__ == "__main__":
    unittest.main()
