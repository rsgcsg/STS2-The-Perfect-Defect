from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from jsonschema import Draft202012Validator
from test_artifact_store_v1 import PRODUCER

from stpd.artifact_contracts import Manifest, Parent, Payload
from stpd.json_boundary import BoundaryError
from stpd.workbench.__main__ import main
from stpd.workbench.developer import (
    ROOT,
    ProjectConfig,
    combination,
    endpoint,
    evidence_identity,
    setup,
)
from stpd.workbench.developer_cli import inspect_policy
from stpd.workbench.developer_server import (
    Application,
    configuration_id,
    create_server,
    instance_lock,
    render,
    running,
    stop_project,
)
from stpd.workbench.hub_client import HubClient


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "project.json"
    setup(path, state_dir=tmp_path / "state", install=False)
    return path, ProjectConfig.load(path)


def test_setup_combination_schema_and_idempotency(project, tmp_path):
    path, config = project
    setup(path, state_dir=config.state_dir, install=False)
    for name, value in (
        ("developer-project-v1", config.to_dict()),
        ("developer-combination-v1", combination()),
    ):
        schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_bytes())
        Draft202012Validator(schema).validate(value)
    with pytest.raises(BoundaryError, match="existing_config_differs"):
        setup(path, state_dir=config.state_dir, hub_url="https://hub.example", install=False)
    value = json.loads(path.read_bytes())
    value["combination"]["platform_source_revision"] = "f" * 40
    path.write_text(json.dumps(value))
    with pytest.raises(BoundaryError, match="combination_changed"):
        ProjectConfig.load(path)


@pytest.mark.parametrize(
    "url",
    [
        "http://public.example",
        "https://secret@hub.example",
        "https://hub.example?token=secret",
        "https://hub.example/#secret",
        "https://hub.example/path",
        "https://hub.example:invalid",
    ],
)
def test_configuration_rejects_credentials_and_unsafe_endpoints(url):
    with pytest.raises(BoundaryError):
        endpoint(url)
    assert endpoint("http://127.0.0.1:8765/") == "http://127.0.0.1:8765"


def test_public_dependency_identity_rejects_sibling_install(monkeypatch):
    class Distribution:
        version = "0.1.0"
        files = []

        def read_text(self, name):
            return json.dumps({"url": "file:///private/sibling", "dir_info": {"editable": True}})

    monkeypatch.setattr("importlib.metadata.distribution", lambda name: Distribution())
    assert evidence_identity("1" * 40)["status"] == "PIN_MISMATCH"


def test_project_cli_redacts_config_errors(project, capsys):
    path, _ = project
    assert (
        main(
            [
                "project",
                "setup",
                "--config",
                str(path),
                "--skip-install",
                "--hub-url",
                "https://secret@hub.example",
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "invalid_endpoint" in output and "secret" not in output
    assert main(["project", "policy"]) == 1


def test_instance_lock_does_not_delete_another_live_owner(tmp_path):
    path = tmp_path / "lock"
    with (
        instance_lock(path),
        pytest.raises(BoundaryError, match="already_running"),
        instance_lock(path),
    ):
        pass
    with instance_lock(path):
        assert path.exists()


def test_local_server_auth_identity_and_safe_render(project):
    _, config = project
    app = Application(config)
    server = create_server(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(url + "/health", timeout=2) as response:
            assert json.load(response)["instance_id"] == app.instance_id
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url + "/api/status", headers={"Host": "attacker.example"}), timeout=2)
        assert error.value.code == 403
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url + "/stop", data=b""), timeout=2)
        assert error.value.code == 403
        (config.state_dir / "runtime.json").write_text(
            json.dumps(
                {
                    "port": server.server_port,
                    "instance_id": app.instance_id,
                    "configuration_id": configuration_id(config),
                    "control_token": app.control_token,
                }
            )
        )
        assert running(config)["instance_id"] == app.instance_id
        assert stop_project(config)["status"] == "stopping"
        thread.join(timeout=3)
        assert not thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
        app.close()
    rendered = render({"delivery": {"message": "<script>x</script>", "token": "secret"}}, "")
    assert "<script>" not in rendered and "&lt;script&gt;" in rendered
    assert "secret" not in rendered


def test_delivery_is_one_owned_public_tool_child(project, tmp_path, monkeypatch):
    _, initial = project
    config_file = tmp_path / "delivery.json"
    config_file.write_text("{}")
    config = ProjectConfig(initial.state_dir, "", "", config_file, initial.combination)
    commands = []

    class Child:
        def __init__(self):
            self.finished = False

        def poll(self):
            return 0 if self.finished else None

        def terminate(self):
            self.finished = True

        def wait(self, timeout):
            return 0

    child = Child()

    def launch(command, **kwargs):
        commands.append(command)
        return child

    app = Application(config)
    monkeypatch.setattr("stpd.workbench.developer_server.subprocess.Popen", launch)
    app.start_delivery()
    assert len(commands) == 1
    assert commands[0][1:] == [
        "-m",
        "sts2_platform_evidence.delivery_cli",
        "run",
        "--config",
        str(config_file),
    ]
    app.close()
    assert child.finished


@pytest.fixture
def hub(monkeypatch):
    payload = b"verified-model-weights"
    manifest = Manifest(
        "model",
        PRODUCER,
        parents=(Parent("run", "a" * 64),),
        payloads=(Payload("weights", hashlib.sha256(payload).hexdigest(), len(payload)),),
    )
    requests = []
    state = {"corrupt": False, "redirect": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(self.path)
            if self.headers.get("Authorization") != "Bearer test-hub-secret":
                self.send_error(401)
                return
            if state["redirect"]:
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/credential-sink")
                self.end_headers()
                return
            if self.path == f"/v1/artifacts/{manifest.artifact_id}":
                value = manifest.to_bytes()
            elif self.path == f"/v1/artifacts/{manifest.artifact_id}/payloads/weights":
                value = b"corrupt" if state["corrupt"] else payload
            elif self.path in {"/v1/status", "/v1/uploads", "/v1/jobs", "/v1/incidents"}:
                value = b'{"items":[]}'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(value)))
            self.end_headers()
            self.wfile.write(value)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("STPD_HUB_TOKEN", "test-hub-secret")
    try:
        yield HubClient(f"http://127.0.0.1:{server.server_port}"), manifest, requests, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_exact_result_download_preserves_manifest_without_parent_payloads(hub, tmp_path):
    client, manifest, requests, _ = hub
    result = client.download(manifest.artifact_id, tmp_path)
    assert result["parents_downloaded"] is False
    assert result["model_load_validated"] is False
    assert (tmp_path / manifest.artifact_id / "manifest.json").read_bytes() == manifest.to_bytes()
    assert "a" * 64 not in str(requests)
    first = len(requests)
    client.download(manifest.artifact_id, tmp_path)
    assert (
        len(requests) == first + 1
    )  # Verify manifest and cached payload; do not redownload bytes.
    file = tmp_path / manifest.artifact_id / result["payloads"][0]["file"]
    file.write_bytes(b"tampered")
    with pytest.raises(BoundaryError, match="existing_payload_mismatch"):
        client.download(manifest.artifact_id, tmp_path)


def test_corrupt_download_never_publishes_success_receipt(hub, tmp_path):
    client, manifest, _, state = hub
    state["corrupt"] = True
    with pytest.raises(BoundaryError, match="payload_integrity_failure"):
        client.download(manifest.artifact_id, tmp_path)
    assert not (tmp_path / manifest.artifact_id / "download.json").exists()
    assert not list(tmp_path.rglob(".pending-*"))


def test_hub_redirection_is_fail_closed_and_token_is_not_exposed(hub):
    client, _, requests, state = hub
    state["redirect"] = True
    with pytest.raises(BoundaryError, match="http_302") as error:
        client.get("/v1/status")
    assert "test-hub-secret" not in str(error.value)
    assert requests == ["/v1/status"]
    assert client.snapshot()["jobs"]["status"] == "unavailable"


def test_policy_inspection_never_loads_or_activates_weights():
    report = inspect_policy(ROOT / "policy-manifests/s1-policy-adapter-v2.json")
    assert report["status"] == "manifest_inspected"
    assert report["loaded"] is False and report["activated"] is False


def test_setup_bootstraps_without_research_dependencies(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "project.json"
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-m",
            "stpd.workbench",
            "project",
            "setup",
            "--skip-install",
            "--config",
            str(path),
            "--state-dir",
            str(tmp_path / "state"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "configured"
    assert ProjectConfig.load(path).state_dir == (tmp_path / "state").resolve()


def test_projection_public_exports_remain_available():
    from stpd.workbench import analyze, project, render_html
    from stpd.workbench.analysis import analyze as analysis
    from stpd.workbench.dashboard import project as projection
    from stpd.workbench.dashboard import render_html as renderer

    assert analyze is analysis and project is projection and render_html is renderer
