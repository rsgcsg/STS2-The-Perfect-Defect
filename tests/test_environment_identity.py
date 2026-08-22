from __future__ import annotations

import copy

import pytest

from stpd.contracts import ContractError
from stpd.environment import environment_identity_from_managed_ready


def _ready() -> dict:
    exact_game = {
        "platform": "darwin",
        "architecture": "arm64",
        "version": "v0.111.0",
        "commit": "41cef1ea",
        "runtime_main_assembly_hash": 1010476334,
        "sts2_dll_sha256": "c" * 64,
        "godotsharp_dll_sha256": "e" * 64,
    }
    return {
        "protocol": "sts2.headless/managed-player-environment-driver-1",
        "headless": {
            "source_revision": "headless-revision",
            "source_worktree_status": "clean",
            "source_digest_sha256": "d" * 64,
        },
        "candidate_manifest": {
            "exact_game": exact_game,
            "expected_build": {
                "artifact_sha256": "a" * 64,
                "artifact_mvid": "22222222-2222-4222-8222-222222222222",
            },
        },
        "exact_game": exact_game,
        "candidate_build": {
            "upstream_revision": "managed-upstream",
            "source_patch_sha256": "b" * 64,
            "artifact_sha256": "a" * 64,
            "artifact_mvid": "22222222-2222-4222-8222-222222222222",
            "runtime_sts2_sha256": "c" * 64,
        },
        "runtime_identity": {
            "host_assembly_sha256": "a" * 64,
            "host_module_mvid": "22222222-2222-4222-8222-222222222222",
            "sts2_assembly_sha256": "c" * 64,
            "sts2_module_mvid": "11111111-1111-4111-8111-111111111111",
        },
        "adapter_runtime_instance_id": "runtime",
        "environment_fingerprint": "fingerprint",
    }


def _snapshot() -> dict:
    return {
        "protocol_version": "1.0.0",
        "session": {
            "runtime_instance_id": "runtime",
            "environment_fingerprint": "fingerprint",
        },
        "information_policy": {"id": "player_visible_v1"},
    }


def test_managed_identity_separates_host_from_player_environment_implementation() -> None:
    identity = environment_identity_from_managed_ready(_ready(), _snapshot())
    assert identity.host_source_revision == "managed-upstream"
    assert identity.host_source_digest_sha256 == "b" * 64
    assert identity.player_environment_revision == "headless-revision"
    assert identity.player_environment_digest_sha256 == "d" * 64
    assert identity.game_artifact_mvid == "11111111-1111-4111-8111-111111111111"


def test_managed_identity_rejects_runtime_or_worktree_drift() -> None:
    drifted = copy.deepcopy(_ready())
    drifted["runtime_identity"]["host_assembly_sha256"] = "f" * 64
    with pytest.raises(ContractError, match="runtime Host SHA"):
        environment_identity_from_managed_ready(drifted, _snapshot())

    dirty = copy.deepcopy(_ready())
    dirty["headless"]["source_worktree_status"] = "dirty"
    with pytest.raises(ContractError, match="clean Headless"):
        environment_identity_from_managed_ready(dirty, _snapshot())
