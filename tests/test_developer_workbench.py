from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from jsonschema import Draft202012Validator
from test_artifact_store_v1 import PRODUCER

from stpd.artifact_contracts import Manifest, Parent, Payload
from stpd.json_boundary import BoundaryError
from stpd.workbench.__main__ import main
from stpd.workbench.developer import (
    PUBLIC_REPOSITORY,
    ROOT,
    ProjectConfig,
    combination,
    doctor,
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


@pytest.fixture
def installed_evidence(tmp_path, monkeypatch):
    """A complete wheel-style identity without executing its package initializer."""
    site = tmp_path / "site-packages"
    package = site / "sts2_platform_evidence"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("raise AssertionError('must not import during doctor')\n")
    (package / "delivery_cli.py").write_text("raise AssertionError('must not run during doctor')\n")
    metadata = site / "rsgcsg_sts2_platform_evidence-0.1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: rsgcsg-sts2-platform-evidence\nVersion: 0.1.0\n")
    (metadata / "direct_url.json").write_text(
        json.dumps(
            {
                "url": PUBLIC_REPOSITORY,
                "vcs_info": {"commit_id": "1" * 40},
                "subdirectory": "components/evidence",
            }
        )
    )
    rows = []
    for path in sorted(site.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            sha = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            # Installed wheel RECORD paths use forward slashes on every platform.
            rows.append(f"{path.relative_to(site).as_posix()},sha256={sha},{len(data)}\n")
    (metadata / "RECORD").write_text("".join(rows))
    distribution = importlib.metadata.Distribution.at(metadata)
    monkeypatch.setattr("importlib.metadata.distribution", lambda name: distribution)
    for name in list(sys.modules):
        if name == "sts2_platform_evidence" or name.startswith("sts2_platform_evidence."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.syspath_prepend(str(site))
    return package, metadata


def test_evidence_record_binds_package_and_delivery_without_import(installed_evidence):
    identity = evidence_identity("1" * 40)
    assert identity["status"] == "PASS"
    assert identity["delivery_entrypoint_verified"] is True
    assert "sts2_platform_evidence" not in sys.modules


@pytest.mark.parametrize("already_loaded", [False, True])
def test_doctor_rejects_import_shadow_even_with_verified_record(
    installed_evidence, project, tmp_path, monkeypatch, already_loaded
):
    package, _ = installed_evidence
    if already_loaded:
        spec = importlib.util.spec_from_file_location(
            "sts2_platform_evidence", package / "__init__.py"
        )
        monkeypatch.setitem(
            sys.modules, "sts2_platform_evidence", importlib.util.module_from_spec(spec)
        )
    shadow = tmp_path / "shadow" / "sts2_platform_evidence"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("raise AssertionError('shadow must not run')\n")
    monkeypatch.syspath_prepend(str(shadow.parent))
    assert evidence_identity("1" * 40)["status"] == "IMPORT_ORIGIN_MISMATCH"
    _, initial = project
    delivery_file = tmp_path / "delivery.json"
    delivery_file.write_text('{"hub_url":"https://hub.example"}')
    config = ProjectConfig(
        initial.state_dir, "https://hub.example", "", delivery_file, initial.combination
    )
    monkeypatch.setattr(
        "stpd.workbench.developer.dependency_checks",
        lambda _: {"evidence": evidence_identity("1" * 40)},
    )
    report = doctor(config)
    assert report["status"] == "BLOCKED"
    assert report["checks"]["delivery_tool"]["status"] == "NOT_VERIFIED"


def test_evidence_rejects_entrypoint_missing_from_record(installed_evidence):
    _, metadata = installed_evidence
    record = metadata / "RECORD"
    rows = record.read_text().splitlines(keepends=True)
    retained = [
        row for row in rows if not row.startswith("sts2_platform_evidence/delivery_cli.py,")
    ]
    assert len(rows) - len(retained) == 1, "the fixture must remove the verified entrypoint"
    record.write_text("".join(retained))
    assert evidence_identity("1" * 40)["status"] == "IMPORT_ORIGIN_MISMATCH"


@pytest.mark.parametrize("owner_status", ["PASS", "BLOCKED"])
def test_doctor_delegates_delivery_readiness_to_isolated_platform_owner(
    project, tmp_path, monkeypatch, owner_status
):
    _, initial = project
    delivery = tmp_path / "delivery.json"
    delivery.write_text("{}")  # The consumer must not maintain a second config parser.
    config = ProjectConfig(
        initial.state_dir, "https://hub.example", "", delivery, initial.combination
    )
    monkeypatch.setattr(
        "stpd.workbench.developer.dependency_checks",
        lambda _: {"evidence": {"status": "PASS", "delivery_entrypoint_verified": True}},
    )
    monkeypatch.setattr("stpd.workbench.developer.tool_identity", lambda: {})
    monkeypatch.setenv("STPD_HUB_ADMIN_TOKEN", "must-not-forward")
    monkeypatch.setenv("PYTHONPATH", "must-not-use")

    def owner(command, **kwargs):
        assert command[:5] == [
            sys.executable,
            "-I",
            "-m",
            "sts2_platform_evidence.delivery_cli",
            "doctor",
        ]
        assert command[-1] == str(delivery)
        assert "STPD_HUB_ADMIN_TOKEN" not in kwargs["env"]
        assert "PYTHONPATH" not in kwargs["env"]
        return subprocess.CompletedProcess(
            command,
            0 if owner_status == "PASS" else 1,
            json.dumps(
                {
                    "schema": "sts2.evidence/delivery-doctor-1",
                    "status": owner_status,
                    "hub_url": "https://hub.example",
                    "discovered_sessions": 7,
                    "checks": {"collection_release": {"status": owner_status}},
                }
            ).encode(),
            b"",
        )

    monkeypatch.setattr("stpd.workbench.developer.subprocess.run", owner)
    report = doctor(config)
    assert report["status"] == owner_status
    assert report["checks"]["delivery_preflight"]["discovered_sessions"] == 7


@pytest.mark.parametrize("response", [b"not-json", b'{"status":"PASS"}'])
def test_doctor_does_not_accept_missing_or_old_platform_preflight(
    project, tmp_path, monkeypatch, response
):
    _, initial = project
    delivery = tmp_path / "delivery.json"
    delivery.write_text("{}")
    config = ProjectConfig(
        initial.state_dir, "https://hub.example", "", delivery, initial.combination
    )
    monkeypatch.setattr(
        "stpd.workbench.developer.dependency_checks",
        lambda _: {"evidence": {"status": "PASS", "delivery_entrypoint_verified": True}},
    )
    monkeypatch.setattr("stpd.workbench.developer.tool_identity", lambda: {})
    monkeypatch.setattr(
        "stpd.workbench.developer.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 0, response, b"private-diagnostic-must-not-return"
        ),
    )
    report = doctor(config)
    assert report["status"] == "BLOCKED"
    assert report["checks"]["delivery_preflight"]["status"] == "UNAVAILABLE"
    assert "private-diagnostic" not in json.dumps(report)


def test_evidence_rejects_loaded_entrypoint_mismatch(installed_evidence, tmp_path, monkeypatch):
    name = "sts2_platform_evidence.delivery_cli"
    module = ModuleType(name)
    module.__file__ = str(tmp_path / "unverified.py")
    module.__spec__ = importlib.util.spec_from_file_location(name, module.__file__)
    monkeypatch.setitem(sys.modules, name, module)
    assert evidence_identity("1" * 40)["status"] == "IMPORT_ORIGIN_MISMATCH"


def test_isolated_delivery_uses_installed_tool_from_hostile_cwd_and_pythonpath(tmp_path):
    shadow = tmp_path / "sts2_platform_evidence"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("raise AssertionError('shadow must not run')\n")
    environment = dict(os.environ, PYTHONPATH=str(tmp_path))
    result = subprocess.run(
        [sys.executable, "-I", "-m", "sts2_platform_evidence.delivery_cli", "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    # Isolating the Platform child does not replace or disable editable STPD.
    editable = subprocess.run(
        [sys.executable, "-I", "-c", "import stpd; print(stpd.__file__)"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert editable.returncode == 0, editable.stderr
    assert Path(editable.stdout.strip()).resolve() == (ROOT / "stpd/__init__.py").resolve()


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
    options = []

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
        options.append(kwargs)
        return child

    app = Application(config)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "shadow"))
    monkeypatch.setenv("PYTHONHOME", str(tmp_path / "shadow-home"))
    monkeypatch.setenv("STPD_HUB_ADMIN_TOKEN", "test-admin")
    monkeypatch.setenv("STPD_HUB_TOKEN", "test-device")
    monkeypatch.setattr("stpd.workbench.developer_server.subprocess.Popen", launch)
    app.start_delivery()
    assert len(commands) == 1
    assert commands[0][1:] == [
        "-I",
        "-m",
        "sts2_platform_evidence.delivery_cli",
        "run",
        "--config",
        str(config_file),
    ]
    assert options[0]["cwd"] == config.state_dir
    environment = options[0]["env"]
    assert not {"PYTHONPATH", "PYTHONHOME", "STPD_HUB_ADMIN_TOKEN"} & environment.keys()
    assert environment["STPD_HUB_TOKEN"] == "test-device"

    def status(command, **kwargs):
        assert command[1:4] == ["-I", "-m", "sts2_platform_evidence.delivery_cli"]
        assert kwargs["cwd"] == config.state_dir and kwargs["env"] == environment
        return subprocess.CompletedProcess(command, 0, b'{"pending":1}')

    monkeypatch.setattr("stpd.workbench.developer_server.subprocess.run", status)
    assert app.delivery_status()["outbox"] == {"pending": 1}
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


def test_invalid_owner_config_does_not_invent_endpoint_mismatch(project, tmp_path, monkeypatch):
    _, initial = project
    delivery = tmp_path / "delivery.json"
    delivery.write_text("{}")
    config = ProjectConfig(initial.state_dir, "https://hub.example", "", delivery,
                           initial.combination)
    monkeypatch.setattr("stpd.workbench.developer.dependency_checks", lambda _: {
        "evidence": {"status": "PASS", "delivery_entrypoint_verified": True}})
    monkeypatch.setattr("stpd.workbench.developer.tool_identity", lambda: {})
    result = {"schema": "sts2.evidence/delivery-doctor-1", "status": "BLOCKED",
              "checks": {"configuration": {"status": "INVALID"}}}
    monkeypatch.setattr("stpd.workbench.developer.subprocess.run", lambda *a, **k:
                        subprocess.CompletedProcess([], 1, json.dumps(result).encode(), b""))
    report = doctor(config)
    assert report["status"] == "BLOCKED"
    assert report["checks"]["delivery_hub"]["status"] == "NOT_CHECKED"
