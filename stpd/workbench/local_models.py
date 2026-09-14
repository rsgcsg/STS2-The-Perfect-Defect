"""Local model preparation and owned Platform Runtime supervision.

Only reviewed registry entries select code. Downloaded manifests are data, never
commands. Platform owns gameplay delivery; this module owns local process and
request state, including uncertain requests that must never be retried.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from ..artifact_contracts import Manifest
from ..canonical import canonical_json
from ..json_boundary import BoundaryError, decode_json, digest, object_fields
from ..package_identity import PackageIdentityError, file_sha256
from .developer import ROOT, ProjectConfig, atomic_json, endpoint
from .hub_client import HubClient, NoRedirect
from .runtime_install import install_runtime, validate_runtime_install

SCHEMA = "stpd/local-models-v1"
RUNTIME_PACKAGE = "@rsgcsg/sts2-policy-runtime"
MODES = frozenset({"human", "shadow", "one_step", "auto"})
JSON_LIMIT = 1024 * 1024


def _object_file(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > JSON_LIMIT:
        raise BoundaryError("local_model", "metadata_missing_or_unsafe")
    value = decode_json(path.read_bytes())
    if not isinstance(value, dict):
        raise BoundaryError("local_model", "invalid_metadata")
    return value


def _inside(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise BoundaryError("local_model", "invalid_registry_path")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise BoundaryError("local_model", "invalid_registry_path")
    return path


def _loopback(url: str) -> str:
    result = endpoint(url)
    if not result.startswith(("http://127.0.0.1:", "http://localhost:", "http://[::1]:")):
        raise BoundaryError("local_model", "loopback_runtime_required")
    return str(result)


def _s1_code_digest(root: Path) -> str:
    # Reading this literal keeps collector inspection free of Torch imports and
    # uses the adapter's own closure inventory instead of a second copied list.
    tree = ast.parse((root / "stpd/policy/adapter.py").read_text(encoding="utf-8"))
    inventory: object = None
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "ADAPTER_SOURCE_CLOSURE"
            for target in statement.targets
        ):
            inventory = ast.literal_eval(statement.value)
    if not isinstance(inventory, tuple) or not inventory:
        raise BoundaryError("local_model", "adapter_source_inventory_missing")
    files = [
        {"path": relative, "sha256": file_sha256(_inside(root, relative))} for relative in inventory
    ]
    return hashlib.sha256(canonical_json(files).encode()).hexdigest()


def _backend_check() -> dict[str, str]:
    if any(importlib.util.find_spec(name) is None for name in ("torch", "transformers")):
        return {"status": "blocked", "code": "install_locked_ml_and_l2_dependencies"}
    if sys.platform == "darwin":
        return {"status": "blocked", "code": "s1_requires_cuda_bf16_backend"}
    script = (
        "import json,torch; print(json.dumps({'available':torch.cuda.is_available() "
        "and torch.cuda.is_bf16_supported()}))"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, timeout=15, check=False
        )
        ready = result.returncode == 0 and json.loads(result.stdout).get("available") is True
        return {
            "status": "pass" if ready else "blocked",
            "code": "cuda_bf16_available" if ready else "s1_requires_cuda_bf16_backend",
        }
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"status": "blocked", "code": "backend_probe_unavailable"}


class RuntimeClient:
    """Bounded loopback transport. A lost POST response is always uncertain."""

    def __init__(self, address: str, startup: dict[str, Any]) -> None:
        self.address = _loopback(address)
        self.startup = startup
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, route: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if route not in {"/status", "/mode", "/tick", "/stop"}:
            raise BoundaryError("local_model", "invalid_runtime_route")
        request = Request(
            self.address + route,
            data=canonical_json(body).encode() if body is not None else None,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=45 if body is not None else 2) as response:
                raw = response.read(JSON_LIMIT + 1)
            if len(raw) > JSON_LIMIT:
                raise ValueError
            value = decode_json(raw)
            expected = "sts2.policy-runtime/http-1" + ("/tick-1" if route == "/tick" else "")
            if not isinstance(value, dict) or value.get("schema") != expected:
                raise ValueError
            status = value.get("status")
            self.validate_status(status)
            return value
        except (HTTPError, URLError, OSError, ValueError, TypeError, BoundaryError):
            raise BoundaryError(
                "local_model",
                "runtime_command_unknown"
                if body is not None
                else "runtime_status_unavailable_or_identity_drift",
            ) from None

    def validate_status(self, status: object) -> None:
        if not isinstance(status, dict):
            raise ValueError
        policy, runtime = status.get("policy"), status.get("runtime")
        if (
            status.get("schema") != "sts2.policy-runtime/status-1"
            or status.get("run_id") != self.startup["run_id"]
            or status.get("mode") not in MODES
            or status.get("lifecycle") not in {"running", "stopped"}
            or status.get("controller") not in {"held", "released"}
            or type(status.get("tainted")) is not bool
            or not isinstance(policy, dict)
            or policy.get("manifest_id") != self.startup["manifest_id"]
            or policy.get("artifact_sha256") != self.startup["policy_artifact_sha256"]
            or not isinstance(runtime, dict)
            or runtime.get("version") != self.startup["runtime_version"]
            or runtime.get("code_sha256") != self.startup["runtime_code_sha256"]
        ):
            raise ValueError


class LocalModelService:
    def __init__(self, config: ProjectConfig, hub: HubClient | None = None) -> None:
        self.config, self.hub = config, hub
        self.root = ROOT
        self.directory = config.state_dir / "models"
        self.lock = threading.RLock()
        self.process: subprocess.Popen[bytes] | None = None
        self.client: RuntimeClient | None = None
        self.thread: threading.Thread | None = None
        self.threads: list[threading.Thread] = []
        self.closed = False
        self.state: dict[str, Any] = {
            "schema": SCHEMA,
            "status": "idle",
            "loaded": False,
            "operation": None,
            "runtime": None,
        }
        previous = self.directory / "session.json"
        if previous.is_file():
            try:
                old = _object_file(previous)
                if old.get("status") not in {"stopped", "idle", "failed"}:
                    self.state.update(
                        status="recovery_required",
                        previous_session=old,
                        error_code="previous_runtime_not_confirmed_stopped",
                    )
            except (OSError, ValueError, BoundaryError):
                self.state.update(status="recovery_required", error_code="session_record_invalid")

    def registry(self) -> dict[str, Any]:
        value = _object_file(self.root / "configs/developer/local-policies-v1.json")
        object_fields(value, {"schema", "runtime_package", "policies"}, "local_model.registry")
        if value["schema"] != "stpd/local-policy-registry-v1" or not isinstance(
            value["policies"], list
        ):
            raise BoundaryError("local_model", "unsupported_registry")
        seen = set()
        for entry in value["policies"]:
            object_fields(
                entry, {"id", "label", "adapter", "manifest", "config"}, "local_model.policy"
            )
            if (
                entry["adapter"] != "s1-v1"
                or not isinstance(entry["id"], str)
                or not re.fullmatch(r"[a-z0-9-]{1,80}", entry["id"])
            ):
                raise BoundaryError("local_model", "unsupported_trusted_adapter")
            if entry["id"] in seen:
                raise BoundaryError("local_model", "duplicate_policy_selection")
            seen.add(entry["id"])
            _inside(self.root, entry["manifest"])
            _inside(self.root, entry["config"])
        return value

    def selection(self, identity: str) -> dict[str, Any]:
        for entry in self.registry()["policies"]:
            if entry["id"] == identity:
                return dict(entry)
        raise BoundaryError("local_model", "unregistered_policy_selection")

    def _runtime_package(self) -> dict[str, Any]:
        pin = self.registry()["runtime_package"]
        if not isinstance(pin, dict) or pin.get("package") != RUNTIME_PACKAGE:
            raise BoundaryError("local_model", "runtime_package_not_pinned")
        try:
            return validate_runtime_install(self._node_modules(), pin, self._connector_pin())
        except (OSError, ValueError, StopIteration, PackageIdentityError):
            raise BoundaryError("local_model", "runtime_package_missing_or_drifted") from None

    def _connector_pin(self) -> dict[str, Any]:
        return next(
            p
            for p in self.config.combination["node_packages"]
            if p.get("package") == "@rsgcsg/sts2-connector-client"
        )

    def _node_modules(self) -> Path:
        private = self.directory / "runtime"
        if private.is_symlink():
            raise BoundaryError("local_model", "runtime_install_path_unsafe")
        return private / "node_modules" if private.exists() else self.root / "node_modules"

    def _public_manifest_contract(self, manifest_path: Path) -> None:
        self._runtime_package()
        script = (
            "import {readFile} from 'node:fs/promises';"
            "const {validatePolicyManifest}=await import(process.argv[1]);"
            "validatePolicyManifest(JSON.parse(await readFile(process.argv[2],'utf8')));"
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "SYSTEMROOT", "SystemRoot", "TMPDIR", "TEMP", "TMP"}
        }
        result = subprocess.run(
            [
                "node",
                "--input-type=module",
                "-e",
                script,
                (self._node_modules() / RUNTIME_PACKAGE / "dist/index.js").as_uri(),
                str(manifest_path),
            ],
            env=environment,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise BoundaryError("local_model", "public_policy_manifest_incompatible")

    def install_runtime(self) -> dict[str, Any]:
        if self.client is not None or (self.process is not None and self.process.poll() is None):
            raise BoundaryError("local_model", "stop_runtime_before_install")

        def install() -> None:
            report = install_runtime(
                self.directory, self.registry()["runtime_package"], self._connector_pin()
            )
            with self.lock:
                self.state.update(status="idle", last_runtime_install=report)

        return self._begin("install-runtime", install)

    def catalog(self) -> dict[str, Any]:
        entries = []
        for entry in self.registry()["policies"]:
            manifest = _object_file(_inside(self.root, entry["manifest"]))
            entries.append(
                {
                    "selection_id": entry["id"],
                    "label": entry["label"],
                    "support": manifest.get("support"),
                    "claims": manifest.get("claims"),
                    "artifact_sha256": manifest.get("artifact", {}).get("sha256"),
                    "readiness": "check_required",
                }
            )
        downloads = []
        parent = self.config.state_dir / "downloads"
        if parent.is_dir():
            for directory in sorted(parent.iterdir()):
                if directory.is_symlink() or not re.fullmatch(r"[a-f0-9]{64}", directory.name):
                    continue
                try:
                    manifest_path = directory / "manifest.json"
                    _object_file(manifest_path)
                    downloaded = Manifest.from_bytes(manifest_path.read_bytes(), directory.name)
                    if downloaded.kind != "model":
                        continue
                    downloads.append(
                        {
                            "artifact_id": downloaded.artifact_id,
                            "kind": downloaded.kind,
                            "model_schema": downloaded.parameters.value().get("schema"),
                            "local_download": (directory / "download.json").is_file(),
                            "loaded": False,
                            "support_status": "unsupported",
                            "reason": "no_compatible_live_adapter_and_input_parity",
                        }
                    )
                except (OSError, ValueError, BoundaryError):
                    continue
        return {
            "schema": SCHEMA,
            "policies": entries,
            "downloaded_models": downloads,
            "session": self.status(),
            "evaluations": self.evaluations(),
            "evaluation_scope": "bounded_runtime_operation",
        }

    def evaluations(self) -> list[dict[str, Any]]:
        directory = self.directory / "evaluations"
        if not directory.is_dir():
            return []
        result = []
        for path in sorted(directory.glob("*.json"))[-100:]:
            try:
                value = _object_file(path)
                identity = value.pop("evaluation_id", None)
                if identity != hashlib.sha256(canonical_json(value).encode()).hexdigest():
                    continue
                result.append({**value, "evaluation_id": identity})
            except (OSError, ValueError, BoundaryError):
                continue
        return result

    def readiness(self, identity: str) -> dict[str, Any]:
        entry = self.selection(identity)
        checks: dict[str, dict[str, str]] = {}
        manifest_path = _inside(self.root, entry["manifest"])
        config_path = _inside(self.root, entry["config"])
        manifest, policy_config = _object_file(manifest_path), _object_file(config_path)

        def check(name: str, operation: Callable[[], object]) -> None:
            try:
                operation()
                checks[name] = {"status": "pass"}
            except (
                OSError,
                ValueError,
                KeyError,
                BoundaryError,
                subprocess.SubprocessError,
            ) as error:
                checks[name] = {
                    "status": "blocked",
                    "code": error.code
                    if isinstance(error, BoundaryError)
                    else name + "_missing_or_drifted",
                }

        def exact_file(path: Path, expected: object) -> None:
            if file_sha256(path) != digest(expected, "local_model.sha256"):
                raise BoundaryError("local_model", "artifact_checksum_mismatch")

        def manifest_check() -> None:
            if (
                manifest.get("schema") != "sts2.policy-runtime/policy-manifest-1"
                or manifest.get("adapter", {}).get("code_sha256") != _s1_code_digest(self.root)
                or manifest.get("artifact", {}).get("sha256") != policy_config["checkpoint_sha256"]
            ):
                raise BoundaryError("local_model", "trusted_policy_identity_drift")
            pin = manifest["adapter_config"]["s1"]["config"]
            if pin["path"] != entry["config"]:
                raise BoundaryError("local_model", "trusted_policy_config_drift")
            exact_file(config_path, pin["sha256"])

        check("policy_identity", manifest_check)
        check("runtime_package", lambda: self._runtime_package() and None)
        check("public_contract", lambda: self._public_manifest_contract(manifest_path))
        check(
            "checkpoint",
            lambda: exact_file(
                _inside(self.root, policy_config["checkpoint_path"]),
                policy_config["checkpoint_sha256"],
            ),
        )
        check(
            "training_ready",
            lambda: exact_file(
                _inside(self.root, policy_config["ready_path"]), policy_config["ready_sha256"]
            ),
        )
        check(
            "checkpoint_sidecar",
            lambda: (
                _object_file(
                    _inside(self.root, policy_config["checkpoint_path"] + ".manifest.json")
                )
                and None
            ),
        )
        checks["backend"] = _backend_check()
        checks["node"] = {
            "status": "pass" if shutil.which("node") else "blocked",
            "code": "node_available" if shutil.which("node") else "node_missing",
        }
        ready = all(value["status"] == "pass" for value in checks.values())
        return {
            "schema": SCHEMA,
            "selection_id": identity,
            "status": "ready_to_load" if ready else "blocked",
            "checks": checks,
            "loaded": False,
            "environment_compatible": "checked_by_runtime_before_decision",
            "qwen_weights": "checked_by_adapter_during_loading",
            "checkpoint_identity": "checked_by_adapter_during_loading",
            "support": manifest["support"],
        }

    def _save(self) -> None:
        atomic_json(self.directory / "session.json", self.state)

    def _begin(
        self, action: str, operation: Callable[[], None], *, recovery: bool = False
    ) -> dict[str, Any]:
        with self.lock:
            if self.closed:
                raise BoundaryError("local_model", "service_closed")
            if self.thread and self.thread.is_alive() and not recovery:
                raise BoundaryError("local_model", "operation_in_progress")
            if self.state["status"] in {"command_unknown", "recovery_required"} and not recovery:
                raise BoundaryError("local_model", "previous_operation_requires_recovery")
            current = {"id": uuid4().hex, "action": action, "status": "pending"}
            self.state["operation"] = current
            self._save()

            def run() -> None:
                try:
                    operation()
                    with self.lock:
                        current["status"] = "completed"
                except (
                    OSError,
                    ValueError,
                    TypeError,
                    KeyError,
                    BoundaryError,
                    subprocess.SubprocessError,
                ) as error:
                    with self.lock:
                        code = (
                            error.code
                            if isinstance(error, BoundaryError)
                            else "local_operation_failed"
                        )
                        if self.state["operation"] is current:
                            self.state.update(
                                status="command_unknown"
                                if code == "runtime_command_unknown"
                                else "failed",
                                error_code=code,
                            )
                        current["status"] = (
                            "unknown" if code == "runtime_command_unknown" else "failed"
                        )
                finally:
                    with self.lock:
                        self._save()

            self.thread = threading.Thread(target=run, daemon=True)
            self.threads = [thread for thread in self.threads if thread.is_alive()]
            self.threads.append(self.thread)
            self.thread.start()
            return cast(dict[str, Any], json.loads(json.dumps(self.state)))

    def prepare(self, artifact_id: str) -> dict[str, Any]:
        identity = digest(artifact_id, "local_model.artifact")
        if self.hub is None:
            raise BoundaryError("local_model", "hub_not_configured")

        def download() -> None:
            assert self.hub is not None
            receipt = self.hub.download(identity, self.config.state_dir / "downloads")
            with self.lock:
                self.state["last_download"] = receipt
                if self.client is None:
                    self.state["status"] = "idle"

        return self._begin("download", download)

    def start(self, identity: str) -> dict[str, Any]:
        self.selection(identity)
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise BoundaryError("local_model", "runtime_already_running")
        return self._begin("start", lambda: self._start(identity))

    def _start(self, identity: str) -> None:
        report = self.readiness(identity)
        with self.lock:
            self.state.update(selection_id=identity, readiness=report)
        if report["status"] != "ready_to_load":
            raise BoundaryError("local_model", "model_readiness_blocked")
        entry = self.selection(identity)
        manifest_path = _inside(self.root, entry["manifest"])
        manifest = _object_file(manifest_path)
        package = self._runtime_package()
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", 15527))
            except OSError:
                raise BoundaryError("local_model", "runtime_port_already_in_use") from None
        connector = _loopback(self.config.platform_url or "http://127.0.0.1:15526")
        command = [
            "node",
            str(self._node_modules() / RUNTIME_PACKAGE / "dist/cli.js"),
            "--manifest",
            str(manifest_path),
            "--adapter-command",
            sys.executable,
            "--adapter-cwd",
            str(self.root),
            "--adapter-arg",
            "tools/policy_adapter.py",
            "--adapter-arg=--config",
            "--adapter-arg",
            entry["config"],
            "--adapter-arg=--manifest",
            "--adapter-arg",
            entry["manifest"],
            "--connector-endpoint",
            connector,
            "--listen-port",
            "15527",
            "--evidence-root",
            str(self.directory / "agent-runs"),
            "--mode",
            "human",
        ]
        environment = dict(os.environ)
        for name in tuple(environment):
            if name.startswith(("STPD_HUB_", "AWS_", "MODAL_", "CLOUDFLARE_")) or name in {
                "PYTHONPATH",
                "PYTHONHOME",
                "NODE_OPTIONS",
            }:
                environment.pop(name, None)
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.lock:
            if self.closed:
                raise BoundaryError("local_model", "service_closed")
            with (self.directory / "runtime.log").open("ab") as log:
                process = subprocess.Popen(
                    command,
                    cwd=self.root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=log,
                )
            self.process = process
            self.state.update(status="loading", loaded=False)
            self._save()
        lines: queue.Queue[bytes] = queue.Queue(maxsize=1)
        stdout = process.stdout
        assert stdout is not None
        threading.Thread(
            target=lambda: lines.put(stdout.readline(JSON_LIMIT + 1)), daemon=True
        ).start()
        try:
            raw = lines.get(timeout=180)
            startup = decode_json(raw)
            if not isinstance(startup, dict) or len(raw) > JSON_LIMIT:
                raise ValueError
            expected = {
                "schema": "sts2.policy-runtime/startup-1",
                "mode": "human",
                "manifest_id": manifest["manifest_id"],
                "policy_artifact_sha256": manifest["artifact"]["sha256"],
                "policy_manifest_sha256": hashlib.sha256(
                    canonical_json(manifest).encode()
                ).hexdigest(),
                "runtime_version": package["version"],
                "runtime_code_sha256": package["code_sha256"],
                "address": "http://127.0.0.1:15527",
            }
            if any(
                startup.get(key) != value for key, value in expected.items()
            ) or not re.fullmatch(r"run-[a-f0-9-]{36}", startup.get("run_id", "")):
                raise ValueError
            client = RuntimeClient(startup["address"], startup)
            runtime = client.request("/status")["status"]
            with self.lock:
                if self.closed:
                    raise BoundaryError("local_model", "service_closed")
                self.client = client
                self.state.update(
                    status="loaded", loaded=True, startup=startup, runtime=runtime, error_code=None
                )
        except (queue.Empty, OSError, ValueError, TypeError, BoundaryError):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            raise BoundaryError("local_model", "runtime_load_or_attestation_failed") from None

    def status(self) -> dict[str, Any]:
        with self.lock:
            client = self.client
            if (
                self.process is not None
                and self.process.poll() is not None
                and self.state["status"] != "stopped"
            ):
                self.state.update(status="runtime_exited", loaded=False)
        if client is not None:
            try:
                runtime = client.request("/status")["status"]
                with self.lock:
                    self.state["runtime"] = runtime
            except BoundaryError as error:
                with self.lock:
                    self.state["observation_error"] = error.code
        with self.lock:
            return cast(dict[str, Any], json.loads(json.dumps(self.state)))

    def command(self, action: str) -> dict[str, Any]:
        if action not in MODES | {"stop"}:
            raise BoundaryError("local_model", "unsupported_local_command")
        with self.lock:
            if self.client is None or not self.state["loaded"]:
                if action in {"human", "stop"} and self.state.get("previous_session"):
                    return self._begin(action, lambda: self._recover(action), recovery=True)
                raise BoundaryError("local_model", "model_not_loaded")

        def execute() -> None:
            client = self.client
            assert client is not None
            # Observe exact instance before every mutation; never address a new
            # process that reused the same port after our owned process exited.
            client.request("/status")
            if action == "stop":
                runtime = client.request("/stop", {})["status"]
            else:
                runtime = client.request("/mode", {"mode": action})["status"]
                if action == "one_step":
                    runtime = client.request("/tick", {"max_ticks": 1})["status"]
            with self.lock:
                if self.state["status"] != "stopped":
                    self.state.update(runtime=runtime, status="loaded", error_code=None)
            if action == "stop":
                self._stop_process()
                self._evaluation_handoff()
                with self.lock:
                    self.state.update(status="stopped", loaded=False)
                    self.client = None

        return self._begin(action, execute, recovery=action in {"human", "stop"})

    def _recover(self, action: str) -> None:
        previous = self.state["previous_session"]
        startup = previous.get("startup")
        entry = self.selection(previous.get("selection_id", ""))
        manifest = _object_file(_inside(self.root, entry["manifest"]))
        package = self._runtime_package()
        if not isinstance(startup, dict) or any(
            startup.get(key) != expected
            for key, expected in {
                "manifest_id": manifest["manifest_id"],
                "policy_artifact_sha256": manifest["artifact"]["sha256"],
                "policy_manifest_sha256": hashlib.sha256(
                    canonical_json(manifest).encode()
                ).hexdigest(),
                "runtime_version": package["version"],
                "runtime_code_sha256": package["code_sha256"],
                "address": "http://127.0.0.1:15527",
            }.items()
        ):
            raise BoundaryError("local_model", "recovery_identity_drift")
        client = RuntimeClient(startup["address"], startup)
        observed = client.request("/status")["status"]
        if observed["lifecycle"] == "running":
            observed = (
                client.request("/stop", {})["status"]
                if action == "stop"
                else (client.request("/mode", {"mode": "human"})["status"])
            )
        with self.lock:
            self.client = client if observed["lifecycle"] == "running" else None
            self.state.update(
                selection_id=entry["id"],
                startup=startup,
                runtime=observed,
                loaded=self.client is not None,
                status="loaded" if self.client is not None else "stopped",
                previous_session=None,
                error_code=None,
            )
        if self.client is None:
            self._evaluation_handoff()

    def _stop_process(self) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def _evaluation_handoff(self) -> None:
        from sts2_platform_evidence import verify_agent_run_evidence

        startup = self.state["startup"]
        directory = self.directory / "agent-runs" / startup["run_id"]
        result = verify_agent_run_evidence(directory, startup)
        report = {
            "schema": "stpd/local-runtime-evaluation-handoff-v1",
            "selection_id": self.state["selection_id"],
            "run_id": startup["run_id"],
            "model_sha256": startup["policy_artifact_sha256"],
            "policy_manifest_sha256": startup["policy_manifest_sha256"],
            "runtime_code_sha256": startup["runtime_code_sha256"],
            "evidence_verification": result.status,
            "findings": [finding.code for finding in result.findings],
            "scope": "bounded_runtime_operation",
            "game_outcome": "not_measured",
            "scientific_verdict": "not_claimed",
            "training_admission": "not_claimed",
        }
        if result.value is not None:
            report.update(
                evidence_content_id=result.value.content_id, event_count=result.value.event_count
            )
            counts: Counter[str] = Counter()
            deliveries: Counter[str] = Counter()
            # Only read events after the owning verifier accepted exact bytes and
            # their relationship to this model/runtime. Counts are operational.
            with (directory / "events.jsonl").open(encoding="utf-8") as events:
                for line in events:
                    event = json.loads(line)
                    counts[event["kind"]] += 1
                    if event["kind"] == "receipt":
                        deliveries[event["payload"]["receipt"]["delivery"]] += 1
            report.update(event_counts=dict(counts), delivery_counts=dict(deliveries))
        identity = hashlib.sha256(canonical_json(report).encode()).hexdigest()
        report["evaluation_id"] = identity
        target = self.directory / "evaluations" / (identity + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = canonical_json(report).encode()
        try:
            with target.open("xb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            if target.is_symlink() or target.read_bytes() != raw:
                raise BoundaryError("local_model", "evaluation_identity_collision") from None
        with self.lock:
            self.state["evaluation"] = report

    def close(self) -> None:
        with self.lock:
            self.closed = True
            client = self.client
        # Human is the only requested state during application shutdown. Do not
        # wait for a long scoring operation before asking the owner to stop.
        try:
            if client is not None:
                client.request("/stop", {})
        except BoundaryError:
            pass
        finally:
            self._stop_process()
        for thread in self.threads:
            thread.join(timeout=1)
        with self.lock:
            if self.client is not None:
                self.state.update(status="stopped", loaded=False)
                try:
                    self._evaluation_handoff()
                except (OSError, ValueError, ImportError):
                    self.state["evidence_status"] = "verification_unavailable"
                self.client = None
            self._save()
