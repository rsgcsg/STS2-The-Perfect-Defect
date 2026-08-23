from __future__ import annotations

import pytest
import torch

from stpd.contracts import QwenIdentity
from stpd.environment import ResearchProjectorV0
from stpd.live import (
    HandoffManager,
    LiveS1Error,
    StaleObservationError,
    admit_snapshot,
    apply_delivery_safety,
    canonicalize_prefetched_reads,
    checkpoint_model_reads,
    refresh_observation_bundle,
    validate_capabilities,
)
from stpd.representation import InputProfile, ModelSerializerV1
from stpd.training import CheckpointIdentity, CheckpointManager, TrainerState


def _snapshot() -> dict:
    return {
        "snapshot_id": "snapshot-live",
        "status": "interactive",
        "persistent": {
            "content": {
                "run": {"ascension": 0},
                "player": {"character_definition_id": "DEFECT"},
            }
        },
        "interaction": {
            "interaction_id": "interaction-live",
            "kind": "combat_turn",
            "content": {
                "surface": {"kind": "combat_turn"},
                "context": {
                    "kind": "combat",
                    "turn_owner": "player",
                    "is_play_phase": True,
                },
            },
            "capabilities": [{"verb": "play"}, {"verb": "end_turn"}],
        },
        "referents": [
            {
                "referent_id": "runtime-card",
                "role": "hand_card",
                "kind": "entity",
                "state": {"visible": True, "observation_basis": "native_visible_fact"},
                "properties": {
                    "entity_id": "native-card",
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
                    "bound_action_id": "bound-play",
                    "verb": "play",
                    "interaction_id": "interaction-live",
                    "subject_referent_id": "runtime-card",
                    "arguments": [],
                    "label": "Play Defend",
                },
                {
                    "bound_action_id": "bound-end",
                    "verb": "end_turn",
                    "interaction_id": "interaction-live",
                    "arguments": [],
                    "label": "End turn",
                },
            ],
        },
        "completeness": {"status": "complete"},
        "information_policy": {"id": "player_visible_v1"},
    }


def test_live_admission_and_projection_preserve_exact_catalog_mapping() -> None:
    snapshot = _snapshot()
    admission = admit_snapshot(snapshot)
    assert admission.available
    assert admission.legal_action_count == 2
    projected = ResearchProjectorV0().project(
        snapshot,
        {},
        game_version="v0.111.0",
        game_commit="41cef1ea",
        mutation_request_prefix="live-test",
    )
    assert [action.kind for action in projected.actions] == ["play_card", "end_turn"]
    assert [envelope.bound_action_id for envelope in projected.envelopes] == [
        "bound-play",
        "bound-end",
    ]
    model_view = str(projected.state.to_dict()) + str(
        [action.to_dict() for action in projected.actions]
    )
    assert "runtime-card" not in model_view
    assert "native-card" not in model_view
    assert "bound-play" not in model_view


def _surface_card_read(read_id: str, target_referent_id: str) -> dict:
    return {
        "read_id": read_id,
        "kind": "surface_card",
        "target_referent_id": target_referent_id,
        "completeness": {"status": "complete"},
    }


def _human_checkpoint_read_policy() -> dict:
    return {
        "mode": "none",
        "training_basis": "human_annotator_importer_empty_reads",
        "standard_reads_line_expected": False,
    }


def test_duplicate_surface_card_reads_retain_identity_and_deterministic_order() -> None:
    first = _surface_card_read("read:surface_card:card-1", "card-1")
    second = _surface_card_read("read:surface_card:card-2", "card-2")

    forward = canonicalize_prefetched_reads([first, second])
    reverse = canonicalize_prefetched_reads([second, first])

    assert forward == reverse
    assert len(forward) == 2
    assert [read["target_referent_id"] for read in forward] == ["card-1", "card-2"]


def test_live_serialization_matches_human_checkpoint_empty_read_semantics() -> None:
    snapshot = _snapshot()
    snapshot["reads"] = [
        _surface_card_read("read:surface_card:card-1", "card-1"),
        _surface_card_read("read:surface_card:card-2", "card-2"),
    ]
    live_reads = checkpoint_model_reads([], _human_checkpoint_read_policy())
    projector = ResearchProjectorV0()
    live = projector.project(
        snapshot,
        live_reads,
        game_version="v0.111.0",
        game_commit="41cef1ea",
        mutation_request_prefix="live",
    )
    training = projector.project(
        snapshot,
        {},
        game_version="v0.111.0",
        game_commit="41cef1ea",
        mutation_request_prefix="training",
    )
    serializer = ModelSerializerV1(InputProfile.STANDARD)

    assert live.state.reads == training.state.reads == {}
    assert serializer.serialize_state(live.state) == serializer.serialize_state(training.state)
    assert "READS=" not in serializer.serialize_state(live.state)


def test_live_checkpoint_policy_rejects_unexpected_prefetched_reads() -> None:
    with pytest.raises(LiveS1Error, match="unexpected prefetched Read"):
        checkpoint_model_reads(
            [_surface_card_read("read:surface_card:card-1", "card-1")],
            _human_checkpoint_read_policy(),
        )


@pytest.mark.parametrize("verb", ["use", "select", "activate", "open", "unknown"])
def test_live_admission_rejects_whole_unsupported_catalog(verb: str) -> None:
    snapshot = _snapshot()
    snapshot["bound_actions"]["actions"][0]["verb"] = verb
    snapshot["interaction"]["capabilities"][0]["verb"] = verb
    admission = admit_snapshot(snapshot)
    assert not admission.available
    assert admission.reason.startswith("UNSUPPORTED_ACTION_CATALOG")


def test_noncombat_and_wrong_run_identity_fail_closed() -> None:
    snapshot = _snapshot()
    snapshot["interaction"]["kind"] = "card_reward"
    assert admit_snapshot(snapshot).reason == "NON_COMBAT_SURFACE:card_reward"
    snapshot = _snapshot()
    snapshot["persistent"]["content"]["run"]["ascension"] = 1
    assert admit_snapshot(snapshot).reason == "REQUIRES_ASCENSION_0"


def test_live_capabilities_bind_exact_connector_only_modset() -> None:
    expected = {
        "protocol_version": "1.0.0",
        "host_kind": "live_ui",
        "connector_source_revision": "source",
        "connector_artifact_sha256": "a" * 64,
        "connector_artifact_mvid": "mvid",
        "game_version": "v0.111.0",
        "game_commit": "41cef1ea",
        "modset_status": "exact_player_environment_only",
        "modset_fingerprint": "fingerprint",
        "loaded_mod_ids": ["STS2_MCP"],
    }
    capabilities = {
        "protocol_version": "1.0.0",
        "host": {
            "host_kind": "live_ui",
            "runtime_instance_id": "runtime",
            "implementation": {
                "source_revision": "source",
                "artifact_sha256": "a" * 64,
                "module_version_id": "mvid",
            },
        },
        "game": {
            "version": "v0.111.0",
            "commit": "41cef1ea",
            "modset": {
                "status": "exact_player_environment_only",
                "fingerprint": "fingerprint",
                "loaded_mod_ids": ["STS2_MCP"],
            },
        },
        "execution_available": True,
        "single_controller": True,
    }
    validate_capabilities(capabilities, expected)
    capabilities["game"]["modset"]["loaded_mod_ids"].append("OTHER")
    with pytest.raises(LiveS1Error, match="loaded_mod_ids drift"):
        validate_capabilities(capabilities, expected)


class _Bridge:
    def __init__(self) -> None:
        self.acquires = 0
        self.releases = 0

    def acquire(self) -> dict:
        self.acquires += 1
        return {"controller": "active"}

    def release(self) -> dict:
        self.releases += 1
        return {"released": True}


def test_human_qwen_handoff_acquires_and_releases() -> None:
    bridge = _Bridge()
    handoff = HandoffManager(bridge)
    assert handoff.mode == "HUMAN"
    assert handoff.toggle_auto()
    handoff.acquire()
    assert handoff.controller_acquired
    handoff.human()
    assert handoff.mode == "HUMAN"
    assert not handoff.controller_acquired
    assert bridge.acquires == bridge.releases == 1


def test_stale_observes_fresh_but_unknown_delivery_never_retries() -> None:
    bridge = _Bridge()
    handoff = HandoffManager(bridge)
    handoff.acquire()
    assert apply_delivery_safety(
        handoff, delivery="not_delivered", reason="stale_snapshot", one_step=False
    ) == "observe_fresh_no_retry"
    assert not handoff.tainted
    assert handoff.controller_acquired
    assert apply_delivery_safety(
        handoff, delivery="unknown", reason="native_delivery_indeterminate", one_step=False
    ) == "stop_no_retry"
    assert handoff.tainted
    assert not handoff.auto_enabled
    assert not handoff.controller_acquired
    assert bridge.acquires == bridge.releases == 1


class _StaleReadThenFreshBridge:
    def __init__(self) -> None:
        self.bundle_attempts = 0
        self.action_submissions: list[str] = []
        self.trace: list[str] = []
        self.read_policies: list[dict | None] = []

    def observe_bundle(self, model_read_policy: dict | None = None) -> dict:
        self.bundle_attempts += 1
        self.read_policies.append(model_read_policy)
        if self.bundle_attempts == 1:
            self.trace.extend(("observe:A", "read:A:409:stale_state", "discard:A"))
            raise StaleObservationError("Read for snapshot A returned HTTP 409 stale_state")
        self.trace.extend(("observe:B", "read:B:coherent"))
        return {
            "snapshot": _snapshot(),
            "reads": [
                _surface_card_read("read:surface_card:card-2", "card-2"),
                _surface_card_read("read:surface_card:card-1", "card-1"),
            ],
        }

    def submit(self, request_id: str) -> None:
        self.action_submissions.append(request_id)


def test_stale_read_discards_bundle_and_fresh_observation_becomes_available() -> None:
    bridge = _StaleReadThenFreshBridge()
    delays: list[float] = []
    stale_events: list[tuple[int, float]] = []
    bundle = refresh_observation_bundle(
        bridge,
        max_attempts=3,
        base_backoff_seconds=0.05,
        model_read_policy={"mode": "all"},
        on_stale=lambda attempt, delay, _error: stale_events.append((attempt, delay)),
        sleeper=delays.append,
    )
    assert bundle is not None
    assert admit_snapshot(bundle["snapshot"]).available
    assert len(canonicalize_prefetched_reads(bundle["reads"])) == 2
    assert bridge.trace == [
        "observe:A",
        "read:A:409:stale_state",
        "discard:A",
        "observe:B",
        "read:B:coherent",
    ]
    assert bridge.bundle_attempts == 2
    assert bridge.read_policies == [{"mode": "all"}, {"mode": "all"}]
    assert stale_events == [(1, 0.05)]
    assert delays == [0.05]
    assert bridge.action_submissions == []


def test_stale_observation_refresh_is_bounded_without_taint_or_submission() -> None:
    class _AlwaysStale:
        def __init__(self) -> None:
            self.attempts = 0
            self.action_submissions: list[str] = []

        def observe_bundle(self) -> dict:
            self.attempts += 1
            raise StaleObservationError("HTTP 409 stale_state")

    bridge = _AlwaysStale()
    delays: list[float] = []
    stale_events: list[tuple[int, float]] = []
    assert refresh_observation_bundle(
        bridge,
        max_attempts=3,
        base_backoff_seconds=0.01,
        on_stale=lambda attempt, delay, _error: stale_events.append((attempt, delay)),
        sleeper=delays.append,
    ) is None
    assert bridge.attempts == 3
    assert delays == [0.01, 0.02]
    assert stale_events == [(1, 0.01), (2, 0.02), (3, 0.0)]
    assert bridge.action_submissions == []


def test_inference_checkpoint_loads_model_only_and_preserves_rng(tmp_path) -> None:
    qwen = QwenIdentity("model", "revision", "revision", "bfloat16", "cuda:0", True)
    identity = CheckpointIdentity(
        "source",
        "manifest",
        "scheme1-linear-pretrained",
        "config",
        "serializer",
        "standard",
        qwen,
    )
    original = torch.nn.Linear(3, 1)
    optimizer = torch.optim.AdamW(original.parameters())
    manager = CheckpointManager()
    checkpoint = tmp_path / "checkpoint.pt"
    state = TrainerState(7, 7, 0, 0)
    manager.save(
        checkpoint,
        model=original,
        optimizer=optimizer,
        identity=identity,
        trainer_state=state,
    )
    restored = torch.nn.Linear(3, 1)
    rng_before = torch.get_rng_state().clone()
    loaded = manager.load_model_for_inference(
        checkpoint, model=restored, expected_identity=identity
    )
    assert loaded == state
    assert torch.equal(torch.get_rng_state(), rng_before)
    assert all(
        torch.equal(left, right)
        for left, right in zip(original.parameters(), restored.parameters(), strict=True)
    )
