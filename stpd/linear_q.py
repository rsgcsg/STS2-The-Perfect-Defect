from __future__ import annotations

from collections.abc import Mapping
import math
import random
from typing import Any


def _combat(snapshot: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if snapshot.get("interaction", {}).get("kind") != "combat_turn":
        return None
    return snapshot.get("interaction", {}).get("content", {}).get("context")


def _player_hp(snapshot: Mapping[str, Any]) -> float:
    return float(snapshot.get("persistent", {}).get("content", {}).get("player", {}).get("hp", 0))


def _floor(snapshot: Mapping[str, Any]) -> int:
    return int(snapshot.get("persistent", {}).get("content", {}).get("run", {}).get("floor", 0))


def _enemy_hp(context: Mapping[str, Any] | None) -> float:
    if context is None:
        return 0.0
    return sum(float(enemy.get("hp", 0)) + float(enemy.get("block", 0)) for enemy in context.get("enemies", []))


def combat_reward(before: Mapping[str, Any], after: Mapping[str, Any]) -> float:
    before_combat = _combat(before)
    if before_combat is None:
        return 0.0
    after_combat = _combat(after)
    enemy_damage = max(0.0, _enemy_hp(before_combat) - _enemy_hp(after_combat))
    player_damage = max(0.0, _player_hp(before) - _player_hp(after))
    reward = enemy_damage * 0.05 - player_damage * 0.10
    if after_combat is None and after.get("interaction", {}).get("kind") != "game_over":
        reward += 1.0
    if after.get("interaction", {}).get("kind") == "game_over":
        victory = after.get("interaction", {}).get("content", {}).get("surface", {}).get("victory") is True
        reward += 10.0 if victory else -5.0
    return reward


def features(snapshot: Mapping[str, Any], action: Mapping[str, Any]) -> dict[str, float]:
    context = _combat(snapshot) or {}
    player = context.get("player", {})
    persistent = snapshot.get("persistent", {}).get("content", {}).get("player", {})
    referents = {item.get("referent_id"): item for item in snapshot.get("referents", [])}
    subject = referents.get(action.get("subject_referent_id"), {}).get("properties", {})
    verb = str(action.get("verb", "unknown"))
    definition = str(subject.get("definition_id", "none"))
    card_type = str(subject.get("type", "none"))
    energy = int(player.get("energy", 0))
    hp = float(persistent.get("hp", 0))
    max_hp = max(1.0, float(persistent.get("max_hp", 1)))
    hp_bucket = min(4, int(5 * hp / max_hp))
    incoming = 0
    for enemy in context.get("enemies", []):
        for intent in enemy.get("intents", []):
            if intent.get("type") == "Attack":
                digits = "".join(character for character in str(intent.get("label", "")) if character.isdigit())
                incoming += int(digits or 0)
    incoming_bucket = min(4, incoming // 5)
    values = {
        "bias": 1.0,
        f"verb:{verb}": 1.0,
        f"definition:{definition}": 1.0,
        f"card_type:{card_type}": 1.0,
        f"energy:{energy}": 1.0,
        f"hp_bucket:{hp_bucket}": 1.0,
        f"incoming_bucket:{incoming_bucket}": 1.0,
        f"verb:{verb}|energy:{energy}": 1.0,
        f"verb:{verb}|hp:{hp_bucket}|incoming:{incoming_bucket}": 1.0,
        f"definition:{definition}|incoming:{incoming_bucket}": 1.0,
    }
    return values


class LinearQ:
    def __init__(self, *, alpha: float = 0.03, gamma: float = 0.95):
        self.alpha = alpha
        self.gamma = gamma
        self.weights: dict[str, float] = {}
        self.updates = 0

    def score(self, snapshot: Mapping[str, Any], action: Mapping[str, Any]) -> float:
        return sum(self.weights.get(name, 0.0) * value for name, value in features(snapshot, action).items())

    def choose(
        self,
        snapshot: Mapping[str, Any],
        actions: list[Mapping[str, Any]],
        rng: random.Random,
        epsilon: float,
    ) -> Mapping[str, Any]:
        if not actions:
            raise ValueError("Cannot choose from an empty action set.")
        if rng.random() < epsilon:
            return rng.choice(actions)
        scored = [(self.score(snapshot, action), index, action) for index, action in enumerate(actions)]
        best = max(score for score, _, _ in scored)
        return rng.choice([action for score, _, action in scored if math.isclose(score, best)])

    def update(
        self,
        snapshot: Mapping[str, Any],
        action: Mapping[str, Any],
        reward: float,
        successor: Mapping[str, Any],
        successor_actions: list[Mapping[str, Any]],
    ) -> float:
        prediction = self.score(snapshot, action)
        continuation = max((self.score(successor, candidate) for candidate in successor_actions), default=0.0)
        delta = max(-10.0, min(10.0, reward + self.gamma * continuation - prediction))
        for name, value in features(snapshot, action).items():
            self.weights[name] = self.weights.get(name, 0.0) + self.alpha * delta * value
        self.updates += 1
        return delta * delta

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": "linear_q_learning",
            "alpha": self.alpha,
            "gamma": self.gamma,
            "updates": self.updates,
            "weights": dict(sorted(self.weights.items())),
        }
