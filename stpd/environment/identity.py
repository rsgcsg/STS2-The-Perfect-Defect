"""Derive exact dataset provenance from one verified Managed PE handshake."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from ..contracts import ContractError, EnvironmentIdentity

MANAGED_DRIVER_PROTOCOL = "sts2.headless/managed-player-environment-driver-1"


def _object(parent: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise ContractError(f"managed identity is missing object: {key}")
    return cast(Mapping[str, Any], value)


def _text(parent: Mapping[str, Any], key: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value:
        raise ContractError(f"managed identity is missing text: {key}")
    return value


def _equal(name: str, left: Any, right: Any) -> None:
    if left != right:
        raise ContractError(f"managed identity mismatch for {name}: {left!r} != {right!r}")


def environment_identity_from_managed_ready(
    ready: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> EnvironmentIdentity:
    """Validate one exact runtime handshake without borrowing Connector runtime identity."""

    _equal("driver protocol", ready.get("protocol"), MANAGED_DRIVER_PROTOCOL)
    headless = _object(ready, "headless")
    if headless.get("source_worktree_status") != "clean":
        raise ContractError("managed collection requires a clean Headless source checkout")
    manifest = _object(ready, "candidate_manifest")
    manifest_game = _object(manifest, "exact_game")
    exact_game = _object(ready, "exact_game")
    _equal("candidate exact game", dict(exact_game), dict(manifest_game))
    expected_build = _object(manifest, "expected_build")
    build = _object(ready, "candidate_build")
    runtime = _object(ready, "runtime_identity")

    _equal(
        "candidate artifact SHA",
        build.get("artifact_sha256"),
        expected_build.get("artifact_sha256"),
    )
    _equal(
        "candidate artifact MVID",
        build.get("artifact_mvid"),
        expected_build.get("artifact_mvid"),
    )
    _equal("runtime Host SHA", runtime.get("host_assembly_sha256"), build.get("artifact_sha256"))
    _equal("runtime Host MVID", runtime.get("host_module_mvid"), build.get("artifact_mvid"))
    _equal(
        "runtime STS2 SHA",
        runtime.get("sts2_assembly_sha256"),
        exact_game.get("sts2_dll_sha256"),
    )
    _equal(
        "runtime build STS2 SHA",
        build.get("runtime_sts2_sha256"),
        exact_game.get("sts2_dll_sha256"),
    )

    session = _object(snapshot, "session")
    _equal(
        "snapshot runtime instance",
        session.get("runtime_instance_id"),
        ready.get("adapter_runtime_instance_id"),
    )
    _equal(
        "snapshot environment fingerprint",
        session.get("environment_fingerprint"),
        ready.get("environment_fingerprint"),
    )
    information_policy = _object(snapshot, "information_policy")
    identity = EnvironmentIdentity(
        game_version=_text(exact_game, "version"),
        game_commit=_text(exact_game, "commit"),
        game_artifact_sha256=_text(runtime, "sts2_assembly_sha256"),
        game_artifact_mvid=_text(runtime, "sts2_module_mvid"),
        host_kind="managed_exact",
        host_source_revision=_text(build, "upstream_revision"),
        host_source_digest_sha256=_text(build, "source_patch_sha256"),
        host_artifact_sha256=_text(runtime, "host_assembly_sha256"),
        host_artifact_mvid=_text(runtime, "host_module_mvid"),
        player_environment_protocol=_text(snapshot, "protocol_version"),
        player_environment_implementation="sts2_headless_managed_adapter",
        player_environment_revision=_text(headless, "source_revision"),
        player_environment_digest_sha256=_text(headless, "source_digest_sha256"),
        information_policy_id=_text(information_policy, "id"),
    )
    identity.validate()
    return identity
