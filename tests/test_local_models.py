from __future__ import annotations

import copy
import hashlib
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from stpd.artifact_contracts import Manifest, Producer
from stpd.canonical import canonical_json
from stpd.json_boundary import BoundaryError, FrozenObject
from stpd.workbench import local_models
from stpd.workbench.developer import ProjectConfig, combination
from stpd.workbench.local_models import LocalModelService, RuntimeClient


@pytest.fixture
def service(tmp_path):
    config = ProjectConfig(tmp_path, "", "", None, combination())
    return LocalModelService(config)


def finished(service):
    assert service.thread is not None
    service.thread.join(timeout=3)
    assert not service.thread.is_alive()
    return service.status()


def startup():
    return {
        "run_id": "run-00000000-0000-0000-0000-000000000000",
        "manifest_id": "fixture-policy",
        "policy_artifact_sha256": "a" * 64,
        "runtime_version": "0.1.0-rc.1",
        "runtime_code_sha256": "b" * 64,
    }


def status():
    start = startup()
    return {
        "schema": "sts2.policy-runtime/status-1",
        "run_id": start["run_id"],
        "runtime": {
            "version": start["runtime_version"],
            "code_sha256": start["runtime_code_sha256"],
        },
        "policy": {
            "manifest_id": start["manifest_id"],
            "artifact_sha256": start["policy_artifact_sha256"],
        },
        "mode": "human",
        "lifecycle": "running",
        "controller": "released",
        "tainted": False,
        "environment": {"host_kind": "test", "loaded_mod_ids": ["STS2_PLATFORM"]},
    }


@pytest.fixture
def runtime_http():
    state = status()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            requests.append((self.path, None))
            self.respond()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            if self.path == "/mode":
                state["mode"] = body["mode"]
            if self.path == "/tick":
                state["mode"] = "human"
            if self.path == "/stop":
                state["lifecycle"] = "stopped"
            self.respond()

        def respond(self):
            value = {"schema": "sts2.policy-runtime/http-1", "status": state}
            if self.path == "/tick":
                value["schema"] += "/tick-1"
                value["results"] = []
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield RuntimeClient(f"http://127.0.0.1:{server.server_port}", startup()), state, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_registry_is_trusted_code_selection_not_downloaded_command(service, tmp_path):
    report = service.catalog()
    assert report["policies"][0]["selection_id"] == "s1-human-combat-v4"
    with pytest.raises(BoundaryError, match="unregistered_policy"):
        service.start("../../downloaded/evil.json")
    root = tmp_path / "untrusted"
    registry = root / "configs/developer/local-policies-v1.json"
    registry.parent.mkdir(parents=True)
    value = service.registry()
    value["policies"][0]["command"] = "sh -c anything"
    registry.write_text(json.dumps(value))
    service.root = root
    with pytest.raises(BoundaryError):
        service.registry()


def test_readiness_reports_real_missing_prerequisites_without_loading(service, monkeypatch):
    monkeypatch.setattr(
        local_models, "_backend_check", lambda: {"status": "blocked", "code": "no_cuda"}
    )
    result = service.readiness("s1-human-combat-v4")
    assert result["status"] == "blocked" and result["loaded"] is False
    assert result["checks"]["policy_identity"]["status"] == "pass"
    assert result["checks"]["backend"]["code"] == "no_cuda"
    assert service.process is None
    service.start("s1-human-combat-v4")
    result = finished(service)
    assert result["error_code"] == "model_readiness_blocked"
    assert service.process is None


def test_runtime_client_accepts_current_environment_and_binds_exact_identity(runtime_http):
    client, state, requests = runtime_http
    assert client.request("/status")["status"]["environment"]["loaded_mod_ids"] == ["STS2_PLATFORM"]
    state["run_id"] = "replacement-runtime"
    with pytest.raises(BoundaryError, match="identity_drift"):
        client.request("/status")
    assert all(body is None for _, body in requests)


@pytest.mark.parametrize(
    "address",
    ["http://public.example:15527", "https://127.0.0.1:15527", "http://127.0.0.1:15527/path"],
)
def test_runtime_requires_loopback_and_no_extra_path(address):
    with pytest.raises(BoundaryError):
        RuntimeClient(address, startup())


def test_one_step_is_exact_owner_mode_and_one_tick(service, runtime_http):
    client, _, requests = runtime_http
    service.client = client
    service.state.update(status="loaded", loaded=True)
    initial = service.command("one_step")
    assert initial["operation"]["action"] == "one_step"
    finished(service)
    assert [r for r in requests if r[1] is not None] == [
        ("/mode", {"mode": "one_step"}),
        ("/tick", {"max_ticks": 1}),
    ]
    assert service.state["runtime"]["mode"] == "human"


def test_lost_tick_response_is_unknown_and_never_retried(service):
    class LostResponse:
        calls = []

        def request(self, route, body=None):
            self.calls.append((route, body))
            if route == "/tick":
                raise BoundaryError("local_model", "runtime_command_unknown")
            return {"status": status()}

    client = LostResponse()
    service.client = client
    service.state.update(status="loaded", loaded=True)
    service.command("one_step")
    assert finished(service)["status"] == "command_unknown"
    with pytest.raises(BoundaryError, match="requires_recovery"):
        service.command("one_step")
    service.command("human")
    finished(service)
    assert sum(route == "/tick" for route, _ in client.calls) == 1


def test_human_handoff_can_be_requested_while_tick_pending(service):
    started, release = threading.Event(), threading.Event()

    class BlockingRuntime:
        def request(self, route, body=None):
            if route == "/tick":
                started.set()
                assert release.wait(timeout=3)
            elif route == "/mode" and body == {"mode": "human"}:
                release.set()
            return {"status": status()}

    service.client = BlockingRuntime()
    service.state.update(status="loaded", loaded=True)
    service.command("one_step")
    assert started.wait(timeout=2)
    service.command("human")
    finished(service)
    for thread in service.threads:
        thread.join(timeout=2)
    assert release.is_set()


def test_restarted_service_does_not_guess_pid_or_activate(service):
    service.state.update(status="loaded", loaded=True, startup=startup())
    service._save()
    replacement = LocalModelService(service.config)
    assert replacement.status()["status"] == "recovery_required"
    assert replacement.client is None and replacement.process is None
    with pytest.raises(BoundaryError, match="requires_recovery"):
        replacement.start("s1-human-combat-v4")


def test_shutdown_during_readiness_cannot_launch_a_late_runtime(service, monkeypatch):
    checking, release = threading.Event(), threading.Event()
    calls = []

    def readiness(_):
        checking.set()
        assert release.wait(timeout=3)
        return {"status": "ready_to_load"}

    monkeypatch.setattr(service, "readiness", readiness)
    monkeypatch.setattr(service, "_runtime_package", lambda: {"version": "fixture"})
    monkeypatch.setattr(local_models.subprocess, "Popen", lambda *a, **k: calls.append(a))
    service.start("s1-human-combat-v4")
    assert checking.wait(timeout=2)
    service.close()
    release.set()
    finished(service)
    assert calls == []
    assert service.state["loaded"] is False


def test_start_uses_fixed_command_human_and_rejects_foreign_attestation(service, monkeypatch):
    monkeypatch.setattr(service, "readiness", lambda _: {"status": "ready_to_load"})
    monkeypatch.setattr(
        service, "_runtime_package", lambda: {"version": "0.1.0-rc.1", "code_sha256": "b" * 64}
    )
    calls = []

    class Process:
        stdout = io.BytesIO(json.dumps({"schema": "foreign"}).encode() + b"\n")
        stopped = False

        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))

        def terminate(self):
            self.stopped = True

        def wait(self, timeout):
            return 0

        def poll(self):
            return 0 if self.stopped else None

    monkeypatch.setattr(local_models.subprocess, "Popen", Process)
    monkeypatch.setenv("STPD_HUB_TOKEN", "must-not-reach-inference-child")
    service.start("s1-human-combat-v4")
    result = finished(service)
    assert result["error_code"] == "runtime_load_or_attestation_failed"
    command, options = calls[0]
    assert command[-2:] == ["--mode", "human"]
    assert "tools/policy_adapter.py" in command
    assert "STPD_HUB_TOKEN" not in options["env"]
    assert service.process.stopped


def test_evaluation_catalog_verifies_content_identity(service):
    directory = service.directory / "evaluations"
    directory.mkdir(parents=True)
    report = {"schema": "stpd/local-runtime-evaluation-handoff-v1", "game_outcome": "not_measured"}
    identity = hashlib.sha256(canonical_json(report).encode()).hexdigest()
    good = {**report, "evaluation_id": identity}
    (directory / (identity + ".json")).write_text(json.dumps(good))
    corrupt = copy.deepcopy(good)
    corrupt["game_outcome"] = "invented win"
    (directory / "corrupt.json").write_text(json.dumps(corrupt))
    assert service.evaluations() == [good]


def test_downloaded_fullrun_model_is_not_treated_as_a_loadable_policy(service):
    model = Manifest(
        "model",
        Producer("test/repository", "a" * 40, "b" * 64),
        parameters=FrozenObject.of({"schema": "stpd/scheme1-model-v1", "command": "malicious"}),
    )
    directory = service.config.state_dir / "downloads" / model.artifact_id
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_bytes(model.to_bytes())
    (directory / "download.json").write_text("{}")
    result = service.catalog()["downloaded_models"]
    assert result[0]["artifact_id"] == model.artifact_id
    assert result[0]["support_status"] == "unsupported" and result[0]["loaded"] is False
    with pytest.raises(BoundaryError, match="unregistered_policy"):
        service.start(model.artifact_id)
    assert service.process is None


def test_prepare_preserves_verified_download_receipt_and_never_starts_runtime(service):
    receipt = {
        "schema": "stpd/result-download-v1",
        "artifact_id": "a" * 64,
        "model_load_validated": False,
        "parents_downloaded": False,
    }

    class Downloader:
        def download(self, identity, destination):
            assert identity == receipt["artifact_id"]
            assert destination == service.config.state_dir / "downloads"
            return receipt

    service.hub = Downloader()
    service.prepare("a" * 64)
    result = finished(service)
    assert result["last_download"] == receipt and result["loaded"] is False
    assert service.process is None


def test_identity_replacement_between_ui_poll_and_command_never_gets_post(service, runtime_http):
    client, state, requests = runtime_http
    service.client = client
    service.state.update(status="loaded", loaded=True)
    assert service.status()["runtime"]["run_id"] == startup()["run_id"]
    state["run_id"] = "some-other-runtime"
    service.command("auto")
    finished(service)
    assert all(body is None for _, body in requests)
