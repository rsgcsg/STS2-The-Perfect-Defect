"""One loopback developer surface supervising the configured Platform delivery tool."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import importlib
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from ..console.page import CSP, asset, render_shell
from ..json_boundary import BoundaryError
from .console import LocalConsole
from .dashboard import _safe_value
from .developer import ROOT, ProjectConfig, atomic_json, doctor, tool_identity
from .hub_client import HubClient


@contextlib.contextmanager
def instance_lock(path: Path) -> Iterator[None]:
    """OS-held lock; process death releases it without PID guesses or stale lock deletion."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        # Windows permits a byte lock beyond EOF; do not read another owner's
        # locked byte merely to initialize the lock file.
        try:
            if os.name == "nt":
                msvcrt = importlib.import_module("msvcrt")

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl = importlib.import_module("fcntl")

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise BoundaryError("project", "already_running") from None
        try:
            yield
        finally:
            if os.name == "nt":
                msvcrt = importlib.import_module("msvcrt")

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl = importlib.import_module("fcntl")

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def configuration_id(config: ProjectConfig) -> str:
    return hashlib.sha256(json.dumps(config.to_dict(), sort_keys=True).encode()).hexdigest()


def _local_request(
    url: str, *, token: str | None = None, timeout: float = 2
) -> dict[str, Any]:
    request = Request(
        url,
        data=b"" if token else None,
        headers={"Authorization": "Bearer " + token} if token else {},
    )
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        value: Any = json.loads(response.read(1024 * 1024))
    if not isinstance(value, dict):
        raise BoundaryError("project", "invalid_local_response")
    return value


def running(config: ProjectConfig) -> dict[str, Any] | None:
    try:
        value = json.loads((config.state_dir / "runtime.json").read_bytes())
        if value["configuration_id"] != configuration_id(config):
            raise BoundaryError("project", "running_configuration_mismatch")
        if not isinstance(value["port"], int) or not 0 < value["port"] < 65536:
            raise ValueError
        observed = _local_request(f"http://127.0.0.1:{value['port']}/health")
        if observed.get("instance_id") != value["instance_id"]:
            raise BoundaryError("project", "runtime_instance_mismatch")
        return cast(dict[str, Any], value)
    except (OSError, ValueError, KeyError):
        return None


def open_project(path: Path, *, browser: bool = True) -> dict[str, Any]:
    config = ProjectConfig.load(path)
    current = running(config)
    if current is None:
        report = doctor(config)
        if report["status"] != "PASS":
            raise BoundaryError("project", "doctor_blocked")
        config.state_dir.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ)
        environment.pop("STPD_HUB_ADMIN_TOKEN", None)
        with (config.state_dir / "logs" / "workbench.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "stpd.workbench", "project", "serve", "--config", str(path)],
                cwd=ROOT,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            current = running(config)
            if current is not None:
                break
            if process.poll() is not None:
                raise BoundaryError("project", "background_start_failed")
            time.sleep(0.1)
        if current is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            raise BoundaryError("project", "background_start_timeout")
    url = f"http://127.0.0.1:{current['port']}/"
    if browser:
        webbrowser.open(url)
    return {
        "status": "running",
        "url": url,
        "instance_id": current["instance_id"],
        "delivery": current["delivery"],
        "gameplay_started": False,
    }


def stop_project(config: ProjectConfig) -> dict[str, Any]:
    current = running(config)
    if current is None:
        return {"status": "not_running"}
    return _local_request(
        f"http://127.0.0.1:{current['port']}/stop", token=current["control_token"]
    )


def status_project(config: ProjectConfig) -> dict[str, Any]:
    current = running(config)
    if current is None:
        return {"status": "not_running"}
    # A snapshot composes a 3-second delivery query and four 2-second Hub reads.
    # Leave response overhead without extending the independent health/stop requests.
    return _local_request(f"http://127.0.0.1:{current['port']}/api/status", timeout=15)


class Application:
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config
        self.instance_id = secrets.token_hex(16)
        self.control_token = secrets.token_hex(32)
        self.identity = tool_identity()
        self.delivery: subprocess.Popen[bytes] | None = None
        self.delivery_log: Any = None
        self.hub = HubClient(config.hub_url, timeout=2) if config.hub_url else None
        self.console = LocalConsole(
            config, self.hub, self.delivery_environment, self.delivery_process, self.identity
        )

    def delivery_process(self) -> str:
        if self.delivery is None:
            return "not_configured"
        return "running" if self.delivery.poll() is None else "stopped"

    @staticmethod
    def delivery_environment() -> dict[str, str]:
        environment = dict(os.environ)
        for name in ("STPD_HUB_ADMIN_TOKEN", "PYTHONPATH", "PYTHONHOME"):
            environment.pop(name, None)
        return environment

    def start_delivery(self) -> None:
        if self.config.delivery_config is None:
            return
        self.delivery_log = (self.config.state_dir / "logs" / "delivery.log").open("ab")
        self.delivery = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-m",
                "sts2_platform_evidence.delivery_cli",
                "run",
                "--config",
                str(self.config.delivery_config),
            ],
            stdin=subprocess.DEVNULL,
            stdout=self.delivery_log,
            stderr=subprocess.STDOUT,
            cwd=self.config.state_dir,
            env=self.delivery_environment(),
        )

    def delivery_status(self) -> dict[str, Any]:
        if self.delivery is None:
            return {"status": "not_configured"}
        code = self.delivery.poll()
        state: dict[str, Any] = {
            "status": "running" if code is None else "stopped",
            "exit_code": code,
        }
        try:
            observed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-m",
                    "sts2_platform_evidence.delivery_cli",
                    "status",
                    "--config",
                    str(self.config.delivery_config),
                ],
                cwd=self.config.state_dir,
                env=self.delivery_environment(),
                capture_output=True,
                timeout=3,
                check=False,
            )
            if observed.returncode == 0:
                state["outbox"] = json.loads(observed.stdout)
            else:
                state["outbox"] = {"status": "unavailable"}
        except (OSError, ValueError, subprocess.SubprocessError):
            state["outbox"] = {"status": "unavailable"}
        return state

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": "stpd/developer-status-v1",
            "instance_id": self.instance_id,
            "identity": self.identity,
            "delivery": self.delivery_status(),
            "hub": self.hub.snapshot() if self.hub else {"status": "not_configured"},
        }

    def close(self) -> None:
        if self.delivery is not None and self.delivery.poll() is None:
            self.delivery.terminate()
            try:
                self.delivery.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.delivery.kill()
                self.delivery.wait(timeout=3)
        if self.delivery_log is not None:
            self.delivery_log.close()


def create_server(app: Application) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def local_host(self) -> bool:
            expected = "127.0.0.1:" + str(cast(ThreadingHTTPServer, self.server).server_port)
            return self.headers.get("Host") == expected

        def respond(self, code: int, value: bytes, content_type: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(value)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                CSP,
            )
            self.end_headers()
            self.wfile.write(value)

        def do_GET(self) -> None:
            if not self.local_host():
                self.respond(403, b"{}")
                return
            parsed = urlsplit(self.path)
            if parsed.path == "/health":
                self.respond(200, json.dumps({"instance_id": app.instance_id}).encode())
            elif parsed.path == "/api/status":
                self.respond(200, json.dumps(_safe_value(app.snapshot())).encode())
            elif parsed.path.startswith("/api/console/"):
                try:
                    value = app.console.route(parsed.path[len("/api/console/"):], parsed.query)
                    self.respond(200, json.dumps(_safe_value(value), ensure_ascii=False).encode())
                except BoundaryError as error:
                    status = 404 if error.code in {"route_not_found", "record_not_found"} else 409
                    self.respond(status, json.dumps({"error": error.code}).encode())
                except (OSError, ValueError, subprocess.SubprocessError):
                    self.respond(503, b'{"error":"observation_unavailable"}')
            elif parsed.path.startswith("/assets/"):
                found = asset(parsed.path[len("/assets/"):])
                if found is None:
                    self.respond(404, b"{}")
                else:
                    kind, data = found
                    self.respond(200, data, kind)
            elif parsed.path == "/":
                self.respond(
                    200, render_shell("local", "/api/console", app.config.hub_url).encode(),
                    "text/html",
                )
            else:
                self.respond(404, b"{}")

        def do_POST(self) -> None:
            if (
                not self.local_host()
                or self.path != "/stop"
                or not hmac.compare_digest(
                    self.headers.get("Authorization", ""), "Bearer " + app.control_token
                )
            ):
                self.respond(403, b"{}")
                return
            self.respond(200, b'{"status":"stopping"}')
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    return server


def serve(config: ProjectConfig) -> dict[str, Any]:
    if doctor(config)["status"] != "PASS":
        raise BoundaryError("project", "doctor_blocked")
    with instance_lock(config.state_dir / "instance.lock"):
        app = Application(config)
        server = create_server(app)
        previous_signal = signal.getsignal(signal.SIGTERM)
        signal.signal(
            signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start()
        )
        try:
            app.start_delivery()
            atomic_json(
                config.state_dir / "runtime.json",
                {
                    "instance_id": app.instance_id,
                    "port": server.server_port,
                    "control_token": app.control_token,
                    "configuration_id": configuration_id(config),
                    "pid": os.getpid(),
                    "identity": app.identity,
                    "delivery": "configured" if config.delivery_config else "not_configured",
                },
            )
            server.serve_forever(poll_interval=0.2)
        finally:
            app.close()
            server.server_close()
            (config.state_dir / "runtime.json").unlink(missing_ok=True)
            signal.signal(signal.SIGTERM, previous_signal)
    return {"status": "stopped"}
