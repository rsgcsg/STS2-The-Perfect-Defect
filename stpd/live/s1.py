"""Exact S1 checkpoint inference behind Connector-owned live authority."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from ..canonical import canonical_json
from ..policy.s1 import (
    DEFAULT_CONFIG,  # noqa: F401
    HUMAN_CHECKPOINT_MODEL_READ_POLICY,  # noqa: F401
    ResidentS1Model,  # noqa: F401
    S1PolicyError,
    SnapshotAdmission,  # noqa: F401
    admit_snapshot,  # noqa: F401
    canonicalize_prefetched_reads,  # noqa: F401
    checkpoint_model_reads,  # noqa: F401
    load_resident_s1,  # noqa: F401
    validate_model_read_policy,  # noqa: F401
)

LiveS1Error = S1PolicyError


class StaleObservationError(LiveS1Error):
    """One Snapshot+Reads transaction raced with a newer Connector snapshot."""


def validate_capabilities(
    capabilities: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    """Bind one live process to the exact game, Connector, protocol, and Modset."""

    host_raw = capabilities.get("host")
    game_raw = capabilities.get("game")
    host = host_raw if isinstance(host_raw, Mapping) else {}
    game = game_raw if isinstance(game_raw, Mapping) else {}
    implementation_raw = host.get("implementation")
    implementation = implementation_raw if isinstance(implementation_raw, Mapping) else {}
    modset_raw = game.get("modset")
    modset = modset_raw if isinstance(modset_raw, Mapping) else {}
    checks = {
        "protocol_version": capabilities.get("protocol_version"),
        "host_kind": host.get("host_kind"),
        "connector_source_revision": implementation.get("source_revision"),
        "connector_artifact_sha256": implementation.get("artifact_sha256"),
        "connector_artifact_mvid": implementation.get("module_version_id"),
        "game_version": game.get("version"),
        "game_commit": game.get("commit"),
        "modset_status": modset.get("status"),
        "modset_fingerprint": modset.get("fingerprint"),
    }
    for name, actual in checks.items():
        if actual != expected.get(name):
            raise LiveS1Error(
                f"live capability {name} drift: expected {expected.get(name)!r}, got {actual!r}"
            )
    loaded_mod_ids = modset.get("loaded_mod_ids")
    if loaded_mod_ids != expected.get("loaded_mod_ids"):
        raise LiveS1Error(
            "live capability loaded_mod_ids drift: "
            f"expected {expected.get('loaded_mod_ids')!r}, got {loaded_mod_ids!r}"
        )
    if capabilities.get("execution_available") is not True:
        raise LiveS1Error("Connector mutation authority is unavailable")
    if capabilities.get("single_controller") is not True:
        raise LiveS1Error("Connector does not declare single-controller authority")
    if not isinstance(host.get("runtime_instance_id"), str) or not host.get(
        "runtime_instance_id"
    ):
        raise LiveS1Error("Connector runtime instance identity is absent")


class ConnectorSdkBridge:
    """Synchronous Python client for the strategy-free official TypeScript SDK bridge."""

    def __init__(
        self,
        *,
        node: Path,
        bridge_script: Path,
        sdk: Path,
        endpoint: str,
        request_timeout_seconds: float = 15.0,
    ) -> None:
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr: list[str] = []
        self._sequence = 0
        self._closed = False
        self._timeout = request_timeout_seconds
        self._process = subprocess.Popen(
            [
                str(node),
                str(bridge_script),
                "--sdk",
                str(sdk),
                "--endpoint",
                endpoint,
                "--timeout-ms",
                str(int(request_timeout_seconds * 1000)),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.request("ping")

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    self._responses.put(cast(dict[str, Any], value))
            except json.JSONDecodeError:
                self._stderr.append(f"non-JSON bridge output: {line.rstrip()}")

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        for line in self._process.stderr:
            self._stderr.append(line.rstrip())
            if len(self._stderr) > 50:
                del self._stderr[:-50]

    def request(self, operation: str, **payload: Any) -> Any:
        if self._closed:
            raise LiveS1Error("Connector SDK bridge is closed")
        self._sequence += 1
        request_id = self._sequence
        message = {"id": request_id, "op": operation, **payload}
        if self._process.poll() is not None or self._process.stdin is None:
            raise LiveS1Error(f"Connector SDK bridge exited: {' | '.join(self._stderr)}")
        self._process.stdin.write(canonical_json(message) + "\n")
        self._process.stdin.flush()
        deadline = time.monotonic() + self._timeout
        deferred: list[dict[str, Any]] = []
        try:
            while time.monotonic() < deadline:
                try:
                    response = self._responses.get(timeout=max(0.01, deadline - time.monotonic()))
                except queue.Empty as error:
                    raise LiveS1Error(
                        f"Connector SDK bridge timed out during {operation}"
                    ) from error
                if response.get("id") != request_id:
                    deferred.append(response)
                    continue
                if response.get("ok") is not True:
                    detail = f"Connector SDK {operation} failed: {response.get('error')}"
                    if (
                        operation == "observe_bundle"
                        and response.get("error_kind") == "transient_observation_race"
                        and response.get("error_code") == "stale_state"
                        and response.get("http_status") == 409
                        and response.get("retry_scope") == "whole_observation_bundle"
                    ):
                        raise StaleObservationError(detail)
                    raise LiveS1Error(detail)
                return response.get("result")
        finally:
            for response in deferred:
                self._responses.put(response)
        raise LiveS1Error(f"Connector SDK bridge timed out during {operation}")

    def connect(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.request("connect"))

    def observe_bundle(self, model_read_policy: Mapping[str, Any]) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.request("observe_bundle", model_read_policy=dict(model_read_policy)),
        )

    def acquire(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.request("acquire"))

    def release(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.request("release"))

    def submit(self, *, request_id: str, snapshot_id: str, bound_action_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.request(
                "submit",
                request_id=request_id,
                expected_snapshot_id=snapshot_id,
                bound_action_id=bound_action_id,
            ),
        )

    def close(self) -> None:
        if self._closed:
            return
        with suppress(LiveS1Error):
            self.request("close")
        self._closed = True
        if self._process.stdin is not None:
            self._process.stdin.close()
        try:
            self._process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._process.terminate()


def refresh_observation_bundle(
    bridge: Any,
    *,
    max_attempts: int,
    base_backoff_seconds: float,
    model_read_policy: Mapping[str, Any] | None = None,
    on_stale: Callable[[int, float, StaleObservationError], None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    """Return one coherent bundle or defer after bounded whole-bundle refreshes.

    A stale Read invalidates its Snapshot and every other Read from that attempt.
    This function performs observation only and has no action-submission port.
    """

    if max_attempts <= 0:
        raise ValueError("observation refresh max_attempts must be positive")
    if base_backoff_seconds < 0:
        raise ValueError("observation refresh backoff must be non-negative")
    for attempt in range(1, max_attempts + 1):
        try:
            if model_read_policy is None:
                return cast(dict[str, Any], bridge.observe_bundle())
            return cast(
                dict[str, Any], bridge.observe_bundle(model_read_policy=model_read_policy)
            )
        except StaleObservationError as error:
            delay = (
                base_backoff_seconds * (2 ** (attempt - 1))
                if attempt < max_attempts
                else 0.0
            )
            if on_stale is not None:
                on_stale(attempt, delay, error)
            if delay:
                sleeper(delay)
    return None


class HandoffManager:
    """Explicit Human/Qwen control state with release on every safety boundary."""

    def __init__(self, bridge: Any) -> None:
        self.bridge = bridge
        self.auto_enabled = False
        self.controller_acquired = False
        self.tainted = False
        self.taint_reason: str | None = None

    @property
    def mode(self) -> str:
        return "QWEN AUTO" if self.auto_enabled else "HUMAN"

    def acquire(self) -> Mapping[str, Any]:
        if self.tainted:
            raise LiveS1Error(f"controller is fail-closed: {self.taint_reason}")
        state = cast(Mapping[str, Any], self.bridge.acquire())
        self.controller_acquired = True
        return state

    def release(self) -> Mapping[str, Any]:
        try:
            state = cast(Mapping[str, Any], self.bridge.release())
        finally:
            self.controller_acquired = False
        return state

    def human(self) -> None:
        self.auto_enabled = False
        if self.controller_acquired:
            self.release()

    def toggle_auto(self) -> bool:
        if self.auto_enabled:
            self.human()
        elif not self.tainted:
            self.auto_enabled = True
        return self.auto_enabled

    def fail_closed(self, reason: str) -> None:
        self.auto_enabled = False
        self.tainted = True
        self.taint_reason = reason
        if self.controller_acquired:
            try:
                self.release()
            except Exception:  # TTL remains the Connector's crash-safe release path.
                self.controller_acquired = False


def apply_delivery_safety(
    handoff: HandoffManager, *, delivery: str, reason: str, one_step: bool
) -> str:
    """Apply the no-retry live delivery policy and return its disposition."""

    if delivery == "unknown":
        handoff.fail_closed(f"UNKNOWN_DELIVERY:{reason}")
        return "stop_no_retry"
    if delivery == "not_delivered":
        if "stale" in reason.lower():
            if one_step and handoff.controller_acquired:
                handoff.release()
            return "observe_fresh_no_retry"
        handoff.fail_closed(f"NOT_DELIVERED:{reason}")
        return "stop_no_retry"
    if delivery == "delivered":
        if one_step and handoff.controller_acquired:
            handoff.release()
        return "delivered"
    handoff.fail_closed(f"UNKNOWN_RECEIPT_DELIVERY:{delivery}")
    raise LiveS1Error(f"unknown receipt delivery classification: {delivery}")


class LiveEvidence:
    """Append-only, local evidence for one experimental live process."""

    def __init__(self, root: Path, manifest: Mapping[str, Any]) -> None:
        root.mkdir(parents=True, exist_ok=False)
        self.root = root
        self.events = root / "events.jsonl"
        (root / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8")

    def append(self, kind: str, **payload: Any) -> None:
        record = {
            "schema": "stpd/experimental-live-s1-event-v1",
            "recorded_at": datetime.now(UTC).isoformat(),
            "kind": kind,
            **payload,
        }
        with self.events.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
