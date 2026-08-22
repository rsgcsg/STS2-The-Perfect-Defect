from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import torch
from tokenizers import Tokenizer, models, pre_tokenizers

from stpd.contracts import QwenBackend
from stpd.models import S2SDTScorer, S2SimpleScorer, Scheme1Scorer
from stpd.qwen.fake_backend import DeterministicFakeQwenBackend, assert_fake_backend_port
from stpd.qwen.l1 import (
    ALLOWLISTED_FILES,
    DECISION_FAMILIES,
    PROFILE_IDS,
    QwenL1Pin,
    QwenL1WeightError,
    SpecialToken,
    cache_snapshot_path,
    inspect_cache,
    is_weight_file,
    load_pin,
    profile_records,
    special_tokens_sha256,
    token_length_summary,
)


class QwenL1Test(unittest.TestCase):
    def test_checked_in_pin_is_immutable_and_complete(self):
        pin = load_pin()
        self.assertEqual(pin.model_id, "Qwen/Qwen3-0.6B-Base")
        self.assertEqual(pin.repo_revision, "da87bfb608c14b7cf20ba1ce41287e8de496c0cd")
        self.assertEqual(tuple(file.name for file in pin.files), ALLOWLISTED_FILES)
        self.assertEqual(tuple(pin.profiles), PROFILE_IDS)
        self.assertEqual(tuple(pin.profiles[PROFILE_IDS[0]]["families"]), DECISION_FAMILIES)
        self.assertEqual(pin.p95_limit, 4096)
        self.assertEqual(pin.hard_limit, 8192)

    def test_weight_names_are_rejected(self):
        self.assertTrue(is_weight_file("model.safetensors"))
        self.assertTrue(is_weight_file("nested/pytorch_model.bin"))
        self.assertFalse(is_weight_file("tokenizer.json"))

    def test_summary_is_nearest_rank_and_fails_hard_without_truncation(self):
        summary = token_length_summary([1, 2, 3, 4, 9000])
        self.assertEqual(summary["p95"], 9000)
        self.assertEqual(summary["max"], 9000)
        self.assertEqual(summary["status"], "fail")
        self.assertTrue(summary["violations"])

    def test_offline_cache_validates_content_and_rejects_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = self._make_tiny_pin(root)
            snapshot = cache_snapshot_path(root / "cache", pin)
            snapshot.mkdir(parents=True)
            self._write_tiny_snapshot(snapshot)
            artifact = inspect_cache(root / "cache", pin)
            self.assertFalse(artifact.weights_downloaded)
            (snapshot / "model.safetensors").write_bytes(b"never load")
            with self.assertRaises(QwenL1WeightError):
                inspect_cache(root / "cache", pin)

    def test_profile_is_stratified_and_rejects_missing_or_overlong_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tokenizer_path = root / "tokenizer.json"
            tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "a": 1}, unk_token="[UNK]"))
            tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
            tokenizer.save(str(tokenizer_path))
            records = [
                {"profile": profile, "family": family, "text": "a"}
                for profile in PROFILE_IDS
                for family in DECISION_FAMILIES
            ]
            report = profile_records(tokenizer_path, records, pin=load_pin())
            self.assertTrue(report["passed"])
            self.assertEqual(report["sample_count"], 9)
            self.assertEqual(
                report["by_profile"][PROFILE_IDS[0]]["by_family"][DECISION_FAMILIES[0]]["p95"],
                1,
            )

            report = profile_records(
                tokenizer_path,
                [{"profile": PROFILE_IDS[0], "family": DECISION_FAMILIES[0], "text": "a " * 9000}],
                pin=load_pin(),
            )
            self.assertFalse(report["passed"])
            self.assertTrue(any("hard limit" in value for value in report["violations"]))

    def test_deterministic_fake_backend_is_a_shape_only_qwen_port(self):
        backend = DeterministicFakeQwenBackend(hidden_size=8, max_tokens=4)
        self.assertIsInstance(backend, QwenBackend)
        assert_fake_backend_port(backend)
        backend.identity.validate_v0()
        self.assertEqual(backend.identity.model_id, "stpd/deterministic-fake-qwen")

        joint = backend.encode_joint(["state one", "state two"], ["play strike", "end turn"])
        self.assertEqual(tuple(joint.shape), (2, 8))
        state_hidden, state_mask = backend.encode_state(["one two", "one"], return_sequence=True)
        self.assertEqual(tuple(state_hidden.shape), (2, 2, 8))
        self.assertEqual(state_mask.tolist(), [[True, True], [True, False]])
        pooled = backend.encode_state(["one two", "one"], return_sequence=False)
        assert isinstance(pooled, torch.Tensor)
        self.assertEqual(tuple(pooled.shape), (2, 8))
        action_hidden, action_mask = backend.embed_action_tokens(["play strike", "end"])
        self.assertEqual(tuple(action_hidden.shape), (2, 2, 8))
        self.assertEqual(action_mask.tolist(), [[True, True], [True, False]])

        repeated = backend.encode_joint(["state one"], ["play strike"])
        torch.testing.assert_close(repeated, backend.encode_joint(["state one"], ["play strike"]))
        self.assertFalse(torch.equal(repeated, backend.encode_joint(["other"], ["play strike"])))

    def test_deterministic_fake_backend_never_silently_caps_sequence(self):
        backend = DeterministicFakeQwenBackend(max_tokens=2)
        with self.assertRaisesRegex(ValueError, "max_tokens=2"):
            backend.encode_state(["one two three"], return_sequence=True)

    def test_deterministic_fake_backend_wires_into_model_shapes(self):
        backend = DeterministicFakeQwenBackend(hidden_size=8, max_tokens=8)
        scheme1 = Scheme1Scorer(backend, 8, head="linear")
        self.assertEqual(tuple(scheme1("state", ("play", "end")).shape), (2,))

        simple = S2SimpleScorer(backend, 8)
        simple_output = simple("state", ("play", "end"))
        self.assertEqual(tuple(simple_output.scores.shape), (2,))
        self.assertEqual(tuple(simple_output.predicted_successors.shape), (2, 8))

        sdt = S2SDTScorer(backend, 8, model_dim=8, world_tokens=2, heads=2, layers=1)
        sdt_output = sdt("state", ("play", "end"))
        self.assertEqual(tuple(sdt_output.scores.shape), (2,))
        self.assertEqual(tuple(sdt_output.predicted_world.shape), (2, 2, 8))

    def _make_tiny_pin(self, root: Path) -> QwenL1Pin:
        files = []
        contents = {
            "config.json": {"model_type": "tiny"},
            "generation_config.json": {},
            "tokenizer_config.json": {"eos_token": "<eos>", "pad_token": "<eos>"},
            "tokenizer.json": {"added_tokens": [{"content": "<eos>", "id": 2, "special": True}]},
            "vocab.json": {},
            "merges.txt": "merge\n",
        }
        for name in ALLOWLISTED_FILES:
            value = contents[name]
            data = (
                value.encode()
                if isinstance(value, str)
                else (json.dumps(value, sort_keys=True) + "\n").encode()
            )
            path = root / name
            path.write_bytes(data)
            kind = (
                "tokenizer"
                if name in {"tokenizer.json", "vocab.json", "merges.txt"}
                else "metadata"
            )
            files.append(
                {
                    "name": name,
                    "kind": kind,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        token = SpecialToken("<eos>", 2, ("eos_token", "pad_token"))
        value = {
            "model_id": "tiny/model",
            "repo_revision": "0" * 40,
            "files": files,
            "special_tokens": [token.to_dict()],
            "special_tokens_sha256": special_tokens_sha256((token,)),
            "config_expectations": {"model_type": "tiny"},
            "profiles": {profile: {"families": list(DECISION_FAMILIES)} for profile in PROFILE_IDS},
            "thresholds": {"p95_max_tokens": 4096, "hard_max_tokens": 8192},
        }
        pin_path = root / "pin.json"
        pin_path.write_text(json.dumps(value), encoding="utf-8")
        return load_pin(pin_path)

    def _write_tiny_snapshot(self, snapshot: Path) -> None:
        contents = {
            "config.json": {"model_type": "tiny"},
            "generation_config.json": {},
            "tokenizer_config.json": {"eos_token": "<eos>", "pad_token": "<eos>"},
            "tokenizer.json": {"added_tokens": [{"content": "<eos>", "id": 2, "special": True}]},
            "vocab.json": {},
            "merges.txt": "merge\n",
        }
        for name, value in contents.items():
            data = (
                value.encode()
                if isinstance(value, str)
                else (json.dumps(value, sort_keys=True) + "\n").encode()
            )
            (snapshot / name).write_bytes(data)


if __name__ == "__main__":
    unittest.main()
