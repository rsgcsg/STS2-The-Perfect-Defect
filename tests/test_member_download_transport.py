"""Real HTTP member downloads retain exact framing when verified storage stops early."""

from __future__ import annotations

import io
import json
import threading
from contextlib import contextmanager
from http.client import IncompleteRead
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest
from test_hub_console import service
from test_hub_console import signed as signed

from stpd.artifact_contracts import Manifest
from stpd.hub.application import HubApplication
from stpd.hub.exports import REQUEST_SCHEMA


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass

    def get_stderr(self):
        # The interrupted storage fixture intentionally raises after headers were sent.
        return io.StringIO()


@contextmanager
def running(app):
    server = make_server("127.0.0.1", 0, app, handler_class=QuietHandler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        assert not worker.is_alive()


@pytest.mark.parametrize("interrupted", [False, True])
def test_member_file_http_auth_framing_and_storage_truncation(
    tmp_path, signed, monkeypatch, interrupted
):
    access, token, _ = signed
    owner = service(tmp_path)
    content = b"abcdef"
    payload = owner.store.put_payload("weights", io.BytesIO(content))
    manifest = Manifest("model", owner.producer, payloads=(payload,))
    owner.store.publish(manifest)
    app = HubApplication(
        owner, "test-admin" * 8, browser_access=access, public_origin="https://hub.example"
    )
    headers = {"Cf-Access-Jwt-Assertion": token()}
    reads = []
    original = owner.store.read_payload

    def stream(item):
        reads.append(item)
        assert item == payload
        if interrupted:
            yield content[:3]
            raise OSError("synthetic storage interruption after three of six bytes")
        yield from original(item)

    monkeypatch.setattr(owner.store, "read_payload", stream)
    with running(app) as root:
        with urlopen(Request(root + "/app/api/identity", headers=headers), timeout=3) as response:
            identity = json.load(response)
        selection = {
            "schema": REQUEST_SCHEMA,
            "collections": [],
            "artifacts": [{"artifact_id": manifest.artifact_id, "roles": ["weights"]}],
            "csrf_token": identity["csrf_token"],
        }
        with urlopen(
            Request(
                root + "/app/api/member/exports",
                data=json.dumps(selection).encode(),
                headers={
                    **headers,
                    "Origin": "https://hub.example",
                    "Content-Type": "application/json",
                },
            ),
            timeout=3,
        ) as response:
            export = json.load(response)
        file = next(item for item in export["files"] if item["role"] == "weights")
        path = root + "/app/api/member/exports/" + export["export_id"] + "/files/" + file["file_id"]
        # A known export/file ID does not bypass signed, currently enrolled membership.
        for denied_headers, status in (
            ({}, 401),
            ({"Authorization": "Bearer " + "one" * 16}, 401),
            ({"Cf-Access-Jwt-Assertion": token(email="uninvited@example.org")}, 403),
        ):
            with pytest.raises(HTTPError) as denied:
                urlopen(Request(path, headers=denied_headers), timeout=3)
            assert denied.value.code == status
            denied.value.close()
        assert reads == []  # Rejected requests never enter the storage stream.
        with urlopen(Request(path, headers=headers), timeout=3) as response:
            assert response.status == 200
            assert response.headers["Content-Length"] == str(len(content)) == "6"
            assert response.headers["Content-Type"] == "application/octet-stream"
            assert response.headers["Content-Disposition"] == (
                'attachment; filename="' + file["file_id"] + '.bin"'
            )
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            if interrupted:
                # Real HTTP EOF must not present a short 200 body as a complete download.
                with pytest.raises(IncompleteRead) as failure:
                    response.read()
                assert failure.value.partial == b"abc"
                assert failure.value.expected == 3
            else:
                assert response.read() == content
        assert reads == [payload]
