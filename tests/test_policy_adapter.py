from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from stpd.canonical import canonical_json
from stpd.contracts import QwenIdentity
from stpd.environment import ResearchProjectorV0
from stpd.policy import (
    PolicyAdapter,
    PolicyAdapterError,
    ResidentS1Model,
    adapter_code_sha256,
    serve_ndjson,
)
from stpd.representation import InputProfile, ModelSerializerV1
from stpd.training.checkpoint import CheckpointIdentity, TrainerState


def _snapshot() -> dict[str, Any]:
    return {
        "snapshot_id": "policy-fixture-snapshot",
        "status": "interactive",
        "persistent": {
            "content": {
                "run": {"ascension": 0},
                "player": {"character_definition_id": "DEFECT"},
            }
        },
        "interaction": {
            "kind": "combat_turn",
            "content": {
                "context": {"kind": "combat", "turn_owner": "player", "is_play_phase": True}
            },
        },
        "referents": [
            {
                "referent_id": "card-runtime",
                "role": "hand_card",
                "kind": "entity",
                "state": {"visible": True},
                "properties": {
                    "definition_id": "DEFEND_DEFECT",
                    "cost": "1",
                    "description": "Gain 5 Block.",
                },
            }
        ],
        "bound_actions": {
            "status": "complete",
            "materialized_count": 2,
            "total_count": 2,
            "actions": [
                {
                    "bound_action_id": "candidate-play",
                    "verb": "play",
                    "subject_referent_id": "card-runtime",
                    "arguments": [],
                },
                {
                    "bound_action_id": "candidate-end",
                    "verb": "end_turn",
                    "arguments": [],
                },
            ],
        },
        "completeness": {"status": "complete"},
        "information_policy": {"id": "player_visible_v1"},
    }


class _FakeScorer:
    training = False

    def score(self, state_text: str, action_texts: tuple[str, ...]) -> list[float]:
        assert state_text
        assert len(action_texts) == 2
        return [0.25, 0.75]


def _fake_model() -> ResidentS1Model:
    qwen = QwenIdentity(
        "fixture-qwen",
        "fixture-revision",
        "fixture-revision",
        "float32",
        "cpu",
        True,
        control="fixture",
    )
    identity = CheckpointIdentity(
        "fixture-source",
        "fixture-data",
        "scheme1-linear-pretrained",
        "fixture-config",
        "stpd-model-serialization-v1",
        InputProfile.STANDARD.value,
        qwen,
    )
    return ResidentS1Model(
        _FakeScorer(),
        ResearchProjectorV0(),
        ModelSerializerV1(InputProfile.STANDARD),
        identity,
        TrainerState(1, 1, 0, 1),
        "f" * 64,
        0.0,
    )


def _adapter_fixture(tmp_path: Path, model: ResidentS1Model | None = None) -> PolicyAdapter:
    config_path = tmp_path / "s1-config.json"
    config = {
        "schema": "stpd/s1-human-combat-live-config-v1",
        "model_read_policy": {
            "mode": "none",
            "training_basis": "human_annotator_importer_empty_reads",
            "standard_reads_line_expected": False,
        },
    }
    config_path.write_text(canonical_json(config) + "\n", encoding="utf-8")
    manifest = {
        "schema": "sts2.policy-runtime/policy-manifest-1",
        "manifest_id": "fixture-manifest",
        "policy": {
            "id": "fixture-policy",
            "version": "1",
            "provider": "stpd",
            "architecture": "fixture",
        },
        "adapter": {
            "id": "stpd-fixture",
            "version": "1",
            "protocol": "sts2.policy-runtime/decision-only-ndjson-1",
            "code_sha256": adapter_code_sha256(),
        },
        "artifact": {
            "id": "fixture-checkpoint",
            "path": "fixture.pt",
            "sha256": "f" * 64,
        },
        "representation": {
            "id": InputProfile.STANDARD.value,
            "version": "stpd-model-serialization-v1",
            "input_schema": "sts2.player-environment/snapshot-1",
        },
        "requirements": {
            "connector_protocol_version": "1.0.0",
            "reads": [],
            "whole_decision_admission": True,
            "candidate_order_digest": "sha256-json-bound-action-id-order",
            "score_count_matches_candidate_count": True,
            "selected_index": True,
            "successor_required": True,
        },
        "support": {
            "game_versions": ["fixture-game"],
            "game_commits": ["fixture-commit"],
            "interaction_kinds": ["combat_turn"],
            "action_verbs": ["play", "end_turn"],
        },
        "adapter_config": {
            "s1": {
                "config": {
                    "path": str(config_path),
                    "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                    "schema": config["schema"],
                },
                "qwen": {
                    "model_id": "fixture-qwen",
                    "model_revision": "fixture-revision",
                    "control": "fixture",
                },
                "serializer": {
                    "version": "stpd-model-serialization-v1",
                    "input_profile": InputProfile.STANDARD.value,
                },
            }
        },
        "claims": {
            "full_run": False,
            "selector": False,
            "catalog_filtered": False,
            "creates_action_authority": False,
            "creates_native_operands": False,
        },
    }
    resident = model or _fake_model()
    return PolicyAdapter(
        config_path=config_path,
        model_loader=lambda _: (resident, config),
        manifest=manifest,
    )


def _decision_request(snapshot: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    identities = [action["bound_action_id"] for action in snapshot["bound_actions"]["actions"]]
    return {
        "run_id": "run-fixture-1",
        "manifest": manifest,
        "bundle": {"observation": snapshot, "reads": []},
        "candidate_count": len(identities),
        "candidate_digest": hashlib.sha256(
            canonical_json(identities).encode("utf-8")
        ).hexdigest(),
    }


def _request_for(adapter: PolicyAdapter, snapshot: dict[str, Any]) -> dict[str, Any]:
    return _decision_request(snapshot, dict(adapter.manifest))


def test_policy_adapter_parity_with_resident_project_and_score(tmp_path: Path) -> None:
    model = _fake_model()
    snapshot = _snapshot()
    direct_decision, direct_actions, direct_scores, _ = model.project_and_score(
        snapshot,
        {},
        game_version="fixture-game",
        game_commit="fixture-commit",
    )
    adapter = _adapter_fixture(tmp_path, model)
    adapter.initialize()
    request = _request_for(adapter, snapshot)
    result = adapter.decide(request)

    assert result["scores"] == direct_scores
    assert result["selected_index"] == max(range(len(direct_scores)), key=direct_scores.__getitem__)
    assert len(direct_decision.actions) == 2
    assert len(direct_actions) == 2
    assert result["candidate_digest"] == request["candidate_digest"]
    assert set(result) == {"candidate_digest", "scores", "selected_index"}


def test_policy_adapter_rejects_incomplete_catalog(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot["bound_actions"]["total_count"] = 3
    adapter = _adapter_fixture(tmp_path)
    adapter.initialize()
    with pytest.raises(PolicyAdapterError, match="candidate catalog is not complete"):
        adapter.decide(_request_for(adapter, snapshot))


def test_policy_adapter_rejects_model_candidate_count_drift(tmp_path: Path) -> None:
    class _DriftingModel:
        def __init__(self) -> None:
            self._base = _fake_model()
            self.checkpoint_sha256 = self._base.checkpoint_sha256
            self.identity = self._base.identity

        def project_and_score(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> tuple[Any, list[str], list[float], float]:
            decision, actions, _, latency = self._base.project_and_score(*args, **kwargs)
            return decision, actions[:1], [0.5], latency

    adapter = _adapter_fixture(tmp_path, _DriftingModel())  # type: ignore[arg-type]
    adapter.initialize()
    with pytest.raises(PolicyAdapterError, match="changed the complete candidate count"):
        adapter.decide(_request_for(adapter, _snapshot()))


def test_policy_adapter_rejects_projector_candidate_reordering(tmp_path: Path) -> None:
    class _ReorderingModel:
        def __init__(self) -> None:
            self._base = _fake_model()
            self.checkpoint_sha256 = self._base.checkpoint_sha256
            self.identity = self._base.identity

        def project_and_score(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> tuple[Any, list[str], list[float], float]:
            decision, actions, scores, latency = self._base.project_and_score(*args, **kwargs)
            reordered = decision.__class__(
                decision.state,
                decision.actions,
                tuple(reversed(decision.envelopes)),
            )
            return reordered, actions, scores, latency

    adapter = _adapter_fixture(tmp_path, _ReorderingModel())  # type: ignore[arg-type]
    adapter.initialize()
    with pytest.raises(PolicyAdapterError, match="reordered the Connector candidate catalog"):
        adapter.decide(_request_for(adapter, _snapshot()))


def test_policy_adapter_rejects_runtime_candidate_order_drift(tmp_path: Path) -> None:
    snapshot = _snapshot()
    adapter = _adapter_fixture(tmp_path)
    adapter.initialize()
    request = _request_for(adapter, snapshot)
    request["candidate_digest"] = "0" * 64
    with pytest.raises(PolicyAdapterError, match="candidate order digest mismatch"):
        adapter.decide(request)


def test_policy_adapter_preserves_live_s1_whole_decision_admission(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot["bound_actions"]["actions"][0]["verb"] = "use"
    adapter = _adapter_fixture(tmp_path)
    adapter.initialize()
    with pytest.raises(PolicyAdapterError, match="whole decision"):
        adapter.decide(_request_for(adapter, snapshot))


def test_policy_adapter_rejects_read_contract_drift(tmp_path: Path) -> None:
    adapter = _adapter_fixture(tmp_path)
    adapter.initialize()
    request = _request_for(adapter, _snapshot())
    request["bundle"]["reads"] = [{"read_id": "read:unexpected"}]
    with pytest.raises(PolicyAdapterError, match="unexpected prefetched"):
        adapter.decide(request)


def test_ndjson_child_protocol_matches_platform_policy_port(tmp_path: Path) -> None:
    prepared = _adapter_fixture(tmp_path)
    prepared.initialize()
    input_value = _request_for(prepared, _snapshot())
    adapter = _adapter_fixture(tmp_path)
    requests = json.dumps(
        {
            "schema": "sts2.policy-runtime/policy-port-1",
            "message_type": "decide",
            "request_id": "request-fixture-1",
            "input": input_value,
        }
    )
    output = io.StringIO()
    assert serve_ndjson(adapter, input_lines=iter(requests.splitlines()), output=output) == 0
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(responses) == 1
    assert responses[0]["schema"] == "sts2.policy-runtime/policy-port-1"
    assert responses[0]["message_type"] == "decision"
    assert responses[0]["request_id"] == "request-fixture-1"
    assert responses[0]["output"] == {
        "candidate_digest": input_value["candidate_digest"],
        "scores": [0.25, 0.75],
        "selected_index": 1,
    }
