from __future__ import annotations

import unittest

from stpd.contracts import (
    ActionScorer,
    ContractError,
    EnvironmentIdentity,
    PlayerEnvironmentPort,
    QwenIdentity,
    TransitionEligibility,
    ensure_score_alignment,
)


class FakeEnvironment:
    ready = {"type": "ready"}

    def reset(self, seed):
        return {"seed": seed}

    def observe(self):
        return {"status": "interactive"}

    def read(self, read_id, snapshot_id):
        return {"read_id": read_id, "snapshot_id": snapshot_id}

    def step(self, bound_action_id, snapshot_id, mutation_request_id=None):
        return {
            "bound_action_id": bound_action_id,
            "snapshot_id": snapshot_id,
            "mutation_request_id": mutation_request_id,
        }

    def close(self):
        return None


class FakeScorer:
    def score(self, model_state, model_actions):
        return [float(index) for index, _ in enumerate(model_actions)]


class ContractTest(unittest.TestCase):
    def test_environment_identity_requires_all_exact_fields(self):
        identity = EnvironmentIdentity(
            game_version="v0.111.0",
            game_commit="41cef1ea",
            game_artifact_sha256="c" * 64,
            game_artifact_mvid="11111111-1111-4111-8111-111111111111",
            host_kind="managed_exact",
            host_source_revision="headless-sha",
            host_source_digest_sha256="d" * 64,
            host_artifact_sha256="a" * 64,
            host_artifact_mvid="22222222-2222-4222-8222-222222222222",
            player_environment_protocol="1.0.0",
            player_environment_implementation="sts2_headless_managed_adapter",
            player_environment_revision="headless-sha",
            player_environment_digest_sha256="d" * 64,
            information_policy_id="player_visible_v1",
        )
        identity.validate()
        with self.assertRaisesRegex(ContractError, "game_version"):
            EnvironmentIdentity(
                "",
                "g",
                "c" * 64,
                "11111111-1111-4111-8111-111111111111",
                "hk",
                "h",
                "d" * 64,
                "a" * 64,
                "22222222-2222-4222-8222-222222222222",
                "1",
                "implementation",
                "revision",
                "d" * 64,
                "p",
            ).validate()
        with self.assertRaisesRegex(ContractError, "host_artifact_sha256"):
            EnvironmentIdentity(
                **{**identity.__dict__, "host_artifact_sha256": "not-a-digest"}
            ).validate()

    def test_transition_eligibility_cannot_be_empty(self):
        TransitionEligibility(True, "full_listwise", False, False, "complete").validate()
        with self.assertRaisesRegex(ContractError, "at least one"):
            TransitionEligibility(False, "none", False, False, "complete").validate()

    def test_qwen_v0_identity_requires_frozen_backbone(self):
        identity = QwenIdentity(
            model_id="Qwen/Qwen3-0.6B-Base",
            model_revision="immutable-revision",
            tokenizer_revision="immutable-tokenizer",
            dtype="bfloat16",
            device="cuda:0",
            frozen=True,
        )
        identity.validate_v0()
        with self.assertRaisesRegex(ContractError, "must be frozen"):
            QwenIdentity("model", "rev", "tok", "float32", "cpu", False).validate_v0()

    def test_runtime_protocols_accept_minimal_implementations(self):
        self.assertIsInstance(FakeEnvironment(), PlayerEnvironmentPort)
        self.assertIsInstance(FakeScorer(), ActionScorer)

    def test_score_alignment_fails_closed(self):
        ensure_score_alignment([1.0, 2.0], ["a", "b"])
        with self.assertRaisesRegex(ContractError, "count mismatch"):
            ensure_score_alignment([1.0], ["a", "b"])
        with self.assertRaisesRegex(ContractError, "empty legal action"):
            ensure_score_alignment([], [])


if __name__ == "__main__":
    unittest.main()
