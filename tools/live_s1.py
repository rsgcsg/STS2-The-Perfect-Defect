#!/usr/bin/env python3
"""Run the exact trained S1 policy behind explicit Human/Connector handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stpd.live import (  # noqa: E402
    ConnectorSdkBridge,
    HandoffManager,
    LiveEvidence,
    LiveS1Error,
    SnapshotAdmission,
    StaleObservationError,
    admit_snapshot,
    apply_delivery_safety,
    canonicalize_prefetched_reads,
    checkpoint_model_reads,
    load_resident_s1,
    refresh_observation_bundle,
    validate_capabilities,
    validate_connector_sdk,
    validate_model_read_policy,
)
from stpd.live.s1 import DEFAULT_CONFIG  # noqa: E402

CONNECTOR_SDK_ROOT = (
    ROOT / "node_modules" / "@rsgcsg" / "sts2-connector-client"
)


class WindowsConsole(Protocol):
    """The two Windows console operations used by the interactive runner."""

    def kbhit(self) -> bool: ...

    def getwch(self) -> str: ...


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_identity(directory: Path, *, require_clean: bool) -> str:
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=directory, text=True
    ).strip()
    if require_clean:
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=directory, text=True
        ).strip()
        if status:
            raise LiveS1Error(f"live source must be clean: {directory}")
    return revision


def node_executable() -> Path:
    found = shutil.which("node")
    if found is None:
        raise LiveS1Error("Node.js is unavailable")
    return Path(found).resolve()


class LiveApplication:
    def __init__(
        self,
        *,
        config_path: Path,
        connector_sdk_root: Path,
        evidence_parent: Path,
    ) -> None:
        print("Loading exact frozen Qwen and S1 checkpoint (one resident instance)...", flush=True)
        self.model, self.config = load_resident_s1(config_path)
        self.model_read_policy = validate_model_read_policy(
            self.config.get("model_read_policy")
        )
        self.source_revision = git_identity(ROOT, require_clean=True)
        sdk_identity = validate_connector_sdk(
            connector_sdk_root, self.config.get("connector_sdk")
        )
        sdk = Path(sdk_identity["entrypoint"])
        self.bridge = ConnectorSdkBridge(
            node=node_executable(),
            bridge_script=ROOT / "tools" / "connector_sdk_bridge.mjs",
            sdk=sdk,
            endpoint=str(self.config["endpoint"]),
        )
        capabilities = self._connect_wait()
        expected = self.config.get("live_identity")
        if not isinstance(expected, Mapping):
            raise LiveS1Error("live identity is absent from config")
        validate_capabilities(capabilities, expected)
        self.capabilities = capabilities
        self.runtime_instance_id = str(capabilities["host"]["runtime_instance_id"])
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        evidence_root = evidence_parent / timestamp
        manifest = {
            "schema": "stpd/experimental-live-s1-manifest-v1",
            "created_at": datetime.now(UTC).isoformat(),
            "non_claim": (
                "experimental live smoke; not scientific Core, B6, or policy quality evidence"
            ),
            "live_source_revision": self.source_revision,
            "training_source_revision": self.model.identity.source_revision,
            "checkpoint_sha256": self.model.checkpoint_sha256,
            "checkpoint_identity_hash": self.model.identity.identity_hash,
            "trainer_state": self.model.trainer_state.__dict__,
            "qwen_identity": self.model.identity.qwen.__dict__,
            "serializer_version": self.model.identity.serializer_version,
            "input_profile": self.model.identity.input_profile,
            "model_read_policy": self.model_read_policy,
            "connector_sdk": sdk_identity,
            "capabilities": capabilities,
            "config_path": str(config_path.resolve()),
            "config_sha256": sha256(config_path.resolve()),
        }
        self.evidence = LiveEvidence(evidence_root, manifest)
        self.handoff = HandoffManager(self.bridge)
        self.last_bundle: dict[str, Any] | None = None
        self.last_admission = SnapshotAdmission(
            False, "WAITING_FOR_SUPPORTED_COMBAT", "none", "none", 0
        )
        self.last_attempted_snapshot: str | None = None
        self.last_choice = "NONE"
        self.last_score = "N/A"
        self.last_latency = "N/A"
        self.last_receipt = "NONE"
        self.connector_status = "READY"
        self.running = True
        self.evidence.append("runner_ready", handoff=self._handoff_state())

    def _connect_wait(self) -> dict[str, Any]:
        deadline = time.monotonic() + 120
        last_error = ""
        while time.monotonic() < deadline:
            try:
                return self.bridge.connect()
            except LiveS1Error as error:
                last_error = str(error)
                print("Waiting for exact Connector host...", flush=True)
                time.sleep(1)
        raise LiveS1Error(f"Connector did not become ready: {last_error}")

    def _handoff_state(self) -> dict[str, Any]:
        return {
            "mode": self.handoff.mode,
            "auto_enabled": self.handoff.auto_enabled,
            "controller_acquired": self.handoff.controller_acquired,
            "tainted": self.handoff.tainted,
            "taint_reason": self.handoff.taint_reason,
        }

    def _assert_runtime(self, snapshot: Mapping[str, Any]) -> None:
        session = snapshot.get("session")
        runtime = session.get("runtime_instance_id") if isinstance(session, Mapping) else None
        if runtime != self.runtime_instance_id:
            self.handoff.fail_closed("RUNTIME_IDENTITY_CHANGED")
            raise LiveS1Error("Connector runtime identity changed; restart the runner")

    @staticmethod
    def _reads_complete(reads: Sequence[Mapping[str, Any]]) -> str | None:
        for read_raw in reads:
            read = read_raw if isinstance(read_raw, Mapping) else {}
            kind = str(read.get("kind", "unknown"))
            completeness = read.get("completeness")
            if not isinstance(completeness, Mapping) or completeness.get("status") != "complete":
                return f"READ_INCOMPLETE:{kind}"
        return None

    def _stale_observation(
        self, attempt: int, delay_seconds: float, error: StaleObservationError
    ) -> None:
        self.last_bundle = None
        self.last_admission = SnapshotAdmission(
            False,
            "REFRESHING_STALE_OBSERVATION",
            self.last_admission.interaction,
            self.last_admission.surface,
            0,
        )
        self.connector_status = "READY"
        self.evidence.append(
            "stale_observation_bundle_discarded",
            attempt=attempt,
            retry_delay_ms=round(delay_seconds * 1000),
            retry_scheduled=delay_seconds > 0,
            error=str(error),
            whole_bundle_discarded=True,
            action_submission_attempted=False,
            handoff=self._handoff_state(),
        )
        self.render()

    def _fresh_bundle(self) -> dict[str, Any] | None:
        refresh = self.config.get("observation_refresh")
        if not isinstance(refresh, Mapping):
            raise LiveS1Error("observation refresh policy is absent from live config")
        return refresh_observation_bundle(
            self.bridge,
            max_attempts=int(refresh["max_attempts"]),
            base_backoff_seconds=float(refresh["base_backoff_ms"]) / 1000,
            model_read_policy=self.model_read_policy,
            on_stale=self._stale_observation,
        )

    def observe(self) -> bool:
        bundle = self._fresh_bundle()
        if bundle is None:
            return False
        snapshot = bundle.get("snapshot")
        if not isinstance(snapshot, Mapping):
            raise LiveS1Error("Connector SDK returned an incomplete decision bundle")
        prefetched_reads = canonicalize_prefetched_reads(bundle.get("reads"))
        model_reads = checkpoint_model_reads(prefetched_reads, self.model_read_policy)
        self._assert_runtime(snapshot)
        admission = admit_snapshot(snapshot)
        read_reason = self._reads_complete(prefetched_reads)
        if admission.available and read_reason:
            admission = SnapshotAdmission(
                False,
                read_reason,
                admission.interaction,
                admission.surface,
                admission.legal_action_count,
            )
        if (
            admission.available
            and str(snapshot.get("snapshot_id")) == self.last_attempted_snapshot
        ):
            admission = SnapshotAdmission(
                False,
                "WAITING_FOR_FRESH_SNAPSHOT",
                admission.interaction,
                admission.surface,
                admission.legal_action_count,
            )
        self.last_bundle = {
            "snapshot": dict(snapshot),
            "prefetched_reads": [dict(read) for read in prefetched_reads],
            "model_reads": model_reads,
        }
        self.last_admission = admission
        if not admission.available and self.handoff.controller_acquired:
            self.handoff.release()
            self.evidence.append(
                "controller_release_unsupported_surface",
                reason=admission.reason,
                handoff=self._handoff_state(),
            )
        return True

    def _stable_successor(self) -> Mapping[str, Any]:
        deadline = time.monotonic() + 20
        while True:
            bundle = self._fresh_bundle()
            if bundle is None:
                if time.monotonic() >= deadline:
                    raise LiveS1Error(
                        "successor observation remained stale for 20 seconds"
                    )
                continue
            snapshot = bundle.get("snapshot")
            if not isinstance(snapshot, Mapping):
                raise LiveS1Error("successor observation is absent")
            self._assert_runtime(snapshot)
            if snapshot.get("status") != "settling":
                return snapshot
            if time.monotonic() >= deadline:
                raise LiveS1Error("successor remained settling for 20 seconds")
            time.sleep(0.05)

    def execute_one(self, *, one_step: bool) -> None:
        if self.last_bundle is None or not self.last_admission.available:
            return
        snapshot = cast(Mapping[str, Any], self.last_bundle["snapshot"])
        prefetched_reads = cast(
            Sequence[Mapping[str, Any]], self.last_bundle["prefetched_reads"]
        )
        model_reads = cast(
            Mapping[str, Mapping[str, Any]], self.last_bundle["model_reads"]
        )
        snapshot_id = str(snapshot["snapshot_id"])
        self.last_attempted_snapshot = snapshot_id
        expected = cast(Mapping[str, Any], self.config["live_identity"])
        decision, action_texts, scores, latency_ms = self.model.project_and_score(
            snapshot,
            model_reads,
            game_version=str(expected["game_version"]),
            game_commit=str(expected["game_commit"]),
        )
        selected_index = max(range(len(scores)), key=scores.__getitem__)
        selected_action = decision.actions[selected_index]
        envelope = decision.envelopes[selected_index]
        raw_actions = snapshot["bound_actions"]["actions"]
        raw_action = raw_actions[selected_index]
        if raw_action["bound_action_id"] != envelope.bound_action_id:
            raise LiveS1Error("projected envelope order differs from Connector catalog")
        candidates = [
            {
                "index": index,
                "semantic_action": action.to_dict(),
                "model_action_sha256": hashlib.sha256(
                    action_texts[index].encode("utf-8")
                ).hexdigest(),
                "score": scores[index],
                "connector_label": raw_actions[index]["label"],
            }
            for index, action in enumerate(decision.actions)
        ]
        self.last_choice = str(raw_action["label"])
        self.last_score = f"{scores[selected_index]:.6f}"
        self.last_latency = f"{latency_ms:.1f} ms"
        self.handoff.acquire()
        self.evidence.append(
            "controller_acquired",
            snapshot_id=snapshot_id,
            handoff=self._handoff_state(),
        )
        try:
            result = self.bridge.submit(
                request_id=envelope.mutation_request_id,
                snapshot_id=envelope.snapshot_id,
                bound_action_id=envelope.bound_action_id,
            )
        except Exception as error:
            self.last_receipt = "UNKNOWN:TRANSPORT_FAILURE"
            self.handoff.fail_closed("UNKNOWN_DELIVERY_TRANSPORT_FAILURE")
            self.evidence.append(
                "decision_unknown_delivery",
                snapshot=dict(snapshot),
                prefetched_reads=[dict(read) for read in prefetched_reads],
                model_reads=dict(model_reads),
                candidates=candidates,
                chosen_index=selected_index,
                latency_ms=latency_ms,
                error=str(error),
                retry_attempted=False,
                handoff=self._handoff_state(),
            )
            return
        receipt_raw = result.get("receipt")
        if not isinstance(receipt_raw, Mapping):
            self.handoff.fail_closed("UNKNOWN_DELIVERY_MISSING_RECEIPT")
            raise LiveS1Error("Connector SDK submission returned no receipt")
        receipt = dict(receipt_raw)
        delivery = str(receipt.get("delivery"))
        reason = str(receipt.get("reason_code") or "NONE")
        self.last_receipt = f"{delivery.upper()}:{reason}"
        if receipt.get("request_id") != envelope.mutation_request_id:
            self.handoff.fail_closed("RECEIPT_REQUEST_ID_MISMATCH")
            raise LiveS1Error("receipt request identity mismatch")
        receipt_action = receipt.get("action")
        if (
            not isinstance(receipt_action, Mapping)
            or receipt_action.get("bound_action_id") != envelope.bound_action_id
        ):
            self.handoff.fail_closed("RECEIPT_ACTION_ID_MISMATCH")
            raise LiveS1Error("receipt action identity mismatch")
        successor: Mapping[str, Any] | None = None
        disposition = apply_delivery_safety(
            self.handoff, delivery=delivery, reason=reason, one_step=one_step
        )
        if delivery == "delivered":
            successor = self._stable_successor()
            if successor.get("snapshot_id") == snapshot_id:
                self.handoff.fail_closed("DELIVERED_WITHOUT_SUCCESSOR_ADVANCE")
                raise LiveS1Error("delivered receipt did not advance snapshot identity")
        self.evidence.append(
            "model_decision",
            snapshot=dict(snapshot),
            prefetched_reads=[dict(read) for read in prefetched_reads],
            model_reads=dict(model_reads),
            candidates=candidates,
            chosen_index=selected_index,
            chosen_action=selected_action.to_dict(),
            execution_envelope={
                "snapshot_id": envelope.snapshot_id,
                "bound_action_id": envelope.bound_action_id,
                "mutation_request_id": envelope.mutation_request_id,
            },
            latency_ms=latency_ms,
            receipt=receipt,
            independent_successor=None if successor is None else dict(successor),
            delivery_disposition=disposition,
            retry_attempted=False,
            handoff=self._handoff_state(),
        )

    def handle_key(self, key: str) -> None:
        normalized = key.upper()
        if normalized == "H":
            self.handoff.human()
            self.evidence.append("human_handoff", handoff=self._handoff_state())
        elif normalized == "T":
            self.handoff.toggle_auto()
            self.evidence.append("auto_toggle", handoff=self._handoff_state())
        elif normalized == "S":
            self.execute_one(one_step=True)
        elif normalized == "Q":
            self.running = False

    def render(self) -> None:
        admission = self.last_admission
        waiting = admission.reason == "WAITING_FOR_SUPPORTED_COMBAT"
        run = "WAITING FOR PLAYER TO START DEFECT A0" if waiting else "LIVE EXPERIMENTAL SMOKE"
        availability = (
            "AVAILABLE" if admission.available and not self.handoff.tainted else "UNAVAILABLE"
        )
        reason = (
            self.handoff.taint_reason
            if self.handoff.tainted
            else admission.reason
        )
        lines = [
            f"CONNECTOR: {self.connector_status}",
            "MODEL: LOADED",
            f"RUN: {run}",
            f"MODE: {self.handoff.mode}",
            f"INTERACTION: {admission.interaction}",
            f"SURFACE: {admission.surface}",
            f"LEGAL ACTIONS: {admission.legal_action_count}",
            f"QWEN TAKEOVER: {availability}",
            f"REASON: {reason}",
            "",
            f"LAST QWEN CHOICE: {self.last_choice}",
            f"LAST SCORE: {self.last_score}",
            f"LAST LATENCY: {self.last_latency}",
            f"LAST RECEIPT: {self.last_receipt}",
            "",
            (
                "T toggle auto | S one supported step | H HUMAN/release | "
                "Q quit runner (game stays open)"
            ),
            f"EVIDENCE: {self.evidence.root}",
        ]
        sys.stdout.write("\x1b[2J\x1b[H" + "\n".join(lines) + "\n")
        sys.stdout.flush()

    def run(self) -> int:
        if os.name != "nt":
            raise LiveS1Error("interactive hotkey runner currently requires Windows")
        msvcrt = cast(WindowsConsole, __import__("msvcrt"))

        try:
            while self.running:
                while msvcrt.kbhit():
                    self.handle_key(msvcrt.getwch())
                try:
                    observed = self.observe()
                    self.connector_status = "READY"
                    if (
                        observed
                        and self.handoff.auto_enabled
                        and self.last_admission.available
                    ):
                        self.execute_one(one_step=False)
                except StaleObservationError as error:
                    # Defensive classification: a stale observe/read is never a
                    # permanent handoff failure, even if a future observation
                    # call site bypasses _fresh_bundle accidentally.
                    self._stale_observation(1, 0, error)
                except Exception as error:
                    self.connector_status = "FAIL-CLOSED"
                    self.handoff.fail_closed(f"RUNTIME_ERROR:{error}")
                    self.evidence.append(
                        "runtime_fail_closed", error=str(error), handoff=self._handoff_state()
                    )
                self.render()
                time.sleep(0.25)
        finally:
            self.handoff.human()
            self.evidence.append("runner_exit", handoff=self._handoff_state())
            self.bridge.close()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("model-check",))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    arguments = parser.parse_args()
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    if arguments.command == "model-check":
        model, config = load_resident_s1(arguments.config)
        print(
            json.dumps(
                {
                    "status": "pass",
                    "checkpoint_sha256": model.checkpoint_sha256,
                    "checkpoint_identity_hash": model.identity.identity_hash,
                    "optimizer_steps": model.trainer_state.optimizer_steps,
                    "qwen_identity": model.identity.qwen.__dict__,
                    "qwen_load_seconds": model.qwen_load_seconds,
                    "config": config["experiment_id"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
