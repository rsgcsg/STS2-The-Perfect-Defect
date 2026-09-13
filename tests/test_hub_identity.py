"""Signed Human approval, credential separation, and durable connection recovery."""

from __future__ import annotations

import concurrent.futures
import io
import json
import sqlite3
import time
from dataclasses import replace

import pytest
from test_hub_console import service
from test_hub_console import signed as signed

from stpd.hub.application import HubApplication
from stpd.hub.console_auth import AccessVerifier
from stpd.hub.database import CURRENT_SCHEMA, Operations, token_hash
from stpd.json_boundary import BoundaryError

ORIGIN = "https://hub.example"
SECRET = "client-secret-" + "a" * 48
ADMIN = "admin" * 16


@pytest.fixture
def hub(tmp_path, signed):
    access, token, _ = signed
    pin, principal = access.principals["owner@example.org"]
    access.principals["owner@example.org"] = (pin, replace(principal, enroll_devices=True))
    return (
        HubApplication(service(tmp_path), ADMIN, browser_access=access, public_origin=ORIGIN),
        token,
        access,
    )


def request(
    app,
    path,
    *,
    method="GET",
    bearer="",
    jwt="",
    body=None,
    origin=ORIGIN,
    source="127.0.0.1",
    query="",
    headers=None,
):
    statuses = []
    raw = json.dumps(body).encode() if body is not None else b""
    result = b"".join(
        app(
            {
                "REQUEST_METHOD": method,
                "PATH_INFO": path,
                "QUERY_STRING": query,
                "REMOTE_ADDR": source,
                "HTTP_AUTHORIZATION": "Bearer " + bearer,
                "HTTP_CF_ACCESS_JWT_ASSERTION": jwt,
                "HTTP_ORIGIN": origin,
                "CONTENT_LENGTH": str(len(raw)),
                "wsgi.input": io.BytesIO(raw),
                **(headers or {}),
            },
            lambda status, headers: statuses.append(status),
        )
    )
    return int(statuses[0].split()[0]), json.loads(result)


def create(app, *, existing=False, secret=SECRET):
    body = {"client_secret": secret, "device_name": "开发终端"}
    if existing:
        body.update(device_id="one", device_token="one" * 16)
    code, result = request(app, "/v1/identity/flows", method="POST", body=body)
    assert code == 201
    return result


def decision(app, token, flow, *, deny=False, changes=None, **kwargs):
    status, identity = request(app, "/app/api/identity", jwt=token)
    assert status == 200
    body = {"csrf_token": identity["csrf_token"], "user_code": flow["user_code"]}
    body.update(changes or {})
    return request(
        app,
        "/app/api/identity/flows/" + flow["flow_id"] + ("/deny" if deny else "/approve"),
        method="POST",
        jwt=token,
        body=body,
        **kwargs,
    )


def poll(app, flow, *, secret=SECRET, ack=False):
    return request(
        app,
        "/v1/identity/flows/" + flow["flow_id"] + ("/ack" if ack else "/poll"),
        method="POST",
        body={"client_secret": secret},
    )


def connected(hub, *, existing=False):
    app, token, _ = hub
    flow = create(app, existing=existing)
    assert decision(app, token(), flow)[0] == 200
    status, result = poll(app, flow)
    assert status == 200 and result["status"] == "approved"
    return flow, result


def test_enrollment_waits_for_human_and_poll_ack_survives_response_loss(hub):
    app, token, _ = hub
    flow = create(app)
    assert flow["approval_path"] == "/app/?view=connect&flow=" + flow["flow_id"]
    assert poll(app, flow)[1] == {"status": "pending"}
    with app.service.operations.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM identity_sessions").fetchone()[0] == 0
    facts = request(app, "/app/api/identity/flows/" + flow["flow_id"], jwt=token())[1]
    assert facts["purpose"] == "enroll_device" and facts["approval_allowed"] is True
    assert facts["recording_consent"] == "not_granted_by_connection"
    assert decision(app, token(), flow)[1] == {"status": "approved"}
    first = poll(app, flow)[1]
    assert poll(app, flow)[1] == first  # No second identity or lost one-time secret.
    identity = request(app, "/v1/identity/me", bearer=first["session_token"])[1]
    device = first["device"]
    assert device["device_id"] in identity["principal"]["device_ids"]
    assert identity["principal"]["email"] == "owner@example.org"
    assert identity["principal"]["subject"] != "known-subject"
    assert "csrf_token" not in identity
    with app.service.operations.transaction() as db:
        serialized = "\n".join(db.iterdump())
        for secret in (SECRET, first["session_token"], device["token"]):
            assert secret not in serialized
        assert db.execute("SELECT COUNT(*) FROM identity_sessions").fetchone()[0] == 1
        row = db.execute("SELECT * FROM devices WHERE id=?", (device["device_id"],)).fetchone()
        assert row["owner_subject"] == identity["principal"]["subject"]
    assert poll(app, flow, ack=True)[1] == {"status": "acknowledged"}
    assert poll(app, flow, ack=True)[1] == {"status": "acknowledged"}
    assert poll(app, flow)[1] == {"status": "denied"}
    assert request(app, "/v1/identity/me", bearer=first["session_token"])[0] == 200


def test_existing_device_requires_proof_and_scope_and_cannot_switch_owner(hub):
    app, token, _ = hub
    for changes in (
        {"device_id": "one"},
        {"device_id": "two", "device_token": "one" * 16},
        {"device_id": "one", "device_token": "wrong" * 16},
    ):
        code, result = request(
            app,
            "/v1/identity/flows",
            method="POST",
            body={
                "client_secret": SECRET,
                "device_name": "Mac",
                **changes,
            },
        )
        assert code in {401, 409} and "token" not in result
    flow, approved = connected(hub, existing=True)
    assert approved["device"] == {"device_id": "one", "name": "开发终端"}
    assert "token" not in approved["device"]
    competing = create(app, existing=True)
    other = token(email="collector@example.org", sub="another-person")
    assert decision(app, other, competing)[0] == 403
    assert poll(app, competing)[1] == {"status": "pending"}
    # A browser account switch never changes the authenticated subject behind an existing token.
    actual = request(app, "/v1/identity/me", bearer=approved["session_token"], jwt=other)[1]
    assert actual["principal"]["email"] == "owner@example.org"


def test_legacy_scope_and_new_device_enrollment_are_separate_grants(hub):
    app, token, _ = hub
    collector = token(email="collector@example.org", sub="collector-sub")
    new = create(app)
    assert decision(app, collector, new)[0] == 403
    existing = create(app, existing=True)
    assert decision(app, collector, existing)[0] == 200
    assert poll(app, existing)[1]["device"]["device_id"] == "one"
    unauthorized = request(
        app,
        "/v1/identity/flows",
        method="POST",
        body={
            "client_secret": SECRET,
            "device_name": "Other",
            "device_id": "two",
            "device_token": "two" * 16,
        },
    )[1]
    assert decision(app, collector, unauthorized)[0] == 403


@pytest.mark.parametrize("origin", ["", "http://hub.example", "https://evil.example", ORIGIN + "/"])
def test_browser_approval_requires_exact_configured_origin(hub, origin):
    app, token, _ = hub
    flow = create(app)
    assert (
        decision(
            app, token(), flow, origin=origin, headers={"HTTP_X_FORWARDED_HOST": "hub.example"}
        )[0]
        == 403
    )
    assert poll(app, flow)[1] == {"status": "pending"}


def test_csrf_is_access_session_bound_and_approval_is_single_use(hub):
    app, token, _ = hub
    flow = create(app)
    first = token()
    csrf = request(app, "/app/api/identity", jwt=first)[1]["csrf_token"]
    second = token(iat=int(time.time()) - 5)
    assert decision(app, second, flow, changes={"csrf_token": csrf})[0] == 403
    assert decision(app, first, flow, changes={"csrf_token": "1.wrong"})[0] == 403
    assert decision(app, first, flow, changes={"user_code": "WRONG123"})[0] == 403
    assert decision(app, first, flow)[0] == 200
    assert decision(app, first, flow)[0] == 409
    assert decision(app, first, flow, deny=True)[0] == 409


def test_denial_expiry_and_wrong_poll_secret_never_issue_credentials(hub):
    app, token, _ = hub
    flow = create(app)
    assert poll(app, flow, secret="wrong" * 12)[0] == 401
    assert decision(app, token(), flow, deny=True)[1] == {"status": "denied"}
    assert poll(app, flow)[1] == {"status": "denied"}
    expired = create(app)
    with app.service.operations.transaction() as db:
        db.execute("UPDATE identity_flows SET expires_at=1 WHERE id=?", (expired["flow_id"],))
    assert poll(app, expired)[1] == {"status": "expired"}
    assert decision(app, token(), expired)[0] == 409
    with app.service.operations.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM identity_sessions").fetchone()[0] == 0


def test_concurrent_approval_issues_one_device_and_one_session(hub):
    app, token, _ = hub
    flow = create(app)
    access = token()
    with concurrent.futures.ThreadPoolExecutor(2) as workers:
        statuses = list(workers.map(lambda _: decision(app, access, flow)[0], range(2)))
    assert sorted(statuses) == [200, 409]
    with app.service.operations.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM identity_sessions").fetchone()[0] == 1


def test_owner_transaction_failure_rolls_back_entire_approval(hub, monkeypatch):
    app, token, _ = hub
    flow = create(app)
    with monkeypatch.context() as scoped:
        scoped.setattr(
            app.service.operations, "_event", lambda *a: (_ for _ in ()).throw(OSError())
        )
        assert decision(app, token(), flow)[0] == 503
    assert poll(app, flow)[1] == {"status": "pending"}
    with app.service.operations.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM identity_users").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM identity_sessions").fetchone()[0] == 0
    assert decision(app, token(), flow)[0] == 200


def test_personal_tokens_are_only_read_console_capabilities(hub):
    app, token, _ = hub
    _, approved = connected(hub)
    personal, device = approved["session_token"], approved["device"]["token"]
    for other in (device, ADMIN, token(), "one" * 16):
        assert request(app, "/v1/identity/me", bearer=other)[0] == 401
        assert request(app, "/v1/identity/logout", bearer=other, method="POST")[0] == 401
    for path in (
        "/v1/identity/device",
        "/v1/console/overview",
        "/v1/uploads",
        "/v1/status",
        "/v1/artifacts/" + "a" * 64,
        "/app/api/overview",
    ):
        assert request(app, path, bearer=personal)[0] == 401
    for path in ("/v1/uploads", "/v1/jobs", "/v1/pause"):
        assert request(app, path, bearer=personal, method="POST", body={})[0] == 401
    assert (
        request(app, "/v1/identity/console/jobs", bearer=personal, method="POST", body={})[0] == 405
    )
    assert request(app, "/v1/identity/console/overview", bearer=personal)[0] == 200
    assert (
        request(app, "/v1/identity/console/datasets", bearer=personal)[1]["availability"]
        == "available"
    )


def test_personal_membership_role_and_enrollment_are_rechecked(hub):
    app, token, access = hub
    _, approved = connected(hub)
    personal, device = approved["session_token"], approved["device"]["token"]
    pin, principal = access.principals["owner@example.org"]
    access.principals["owner@example.org"] = (
        pin,
        replace(principal, role="collector", enroll_devices=False),
    )
    assert (
        request(app, "/v1/identity/console/datasets", bearer=personal)[1]["availability"]
        == "not_authorized"
    )
    me = request(app, "/v1/identity/me", bearer=personal)[1]
    assert me["principal"]["enroll_devices"] is False
    assert approved["device"]["device_id"] in me["principal"]["device_ids"]
    assert decision(app, token(), create(app))[0] == 403
    del access.principals["owner@example.org"]
    assert request(app, "/v1/identity/me", bearer=personal)[0] == 401
    assert request(app, "/v1/identity/device", bearer=device)[0] == 200
    assert request(app, "/v1/identity/logout", method="POST", bearer=personal)[0] == 200


def test_session_expiry_logout_and_device_revoke_are_independent(hub):
    app, _, _ = hub
    _, approved = connected(hub)
    personal, device = approved["session_token"], approved["device"]["token"]
    ops = app.service.operations
    with ops.transaction() as db:
        expiry = db.execute("SELECT expires_at FROM identity_sessions").fetchone()[0]
        assert time.time() < expiry < time.time() + 61  # Access expiry caps the 24h lifetime.
        db.execute("UPDATE identity_sessions SET expires_at=1")
    assert request(app, "/v1/identity/me", bearer=personal)[0] == 401
    assert request(app, "/v1/identity/device", bearer=device)[0] == 200
    _, approved2 = connected(hub, existing=True)
    personal2 = approved2["session_token"]
    assert request(app, "/v1/identity/logout", method="POST", bearer=personal2)[1] == {
        "status": "logged_out"
    }
    assert request(app, "/v1/identity/me", bearer=personal2)[0] == 401
    assert request(app, "/v1/identity/device", bearer="one" * 16)[0] == 200
    ops.revoke(approved["device"]["device_id"])
    assert request(app, "/v1/identity/device", bearer=device)[0] == 401


def test_device_heartbeat_reports_observation_not_presence_and_rotates_in_place(hub):
    app, _, _ = hub
    _, approved = connected(hub, existing=True)
    ops = app.service.operations
    upload = ops.create_upload("one", "a" * 64, "b" * 64, {"original": "intent"})
    before = ops.upload(upload["id"])
    assert request(app, "/v1/identity/device", bearer="one" * 16)[1]["last_seen"] is None
    seen = request(
        app,
        "/v1/identity/device/heartbeat",
        bearer="one" * 16,
        method="POST",
        body={"version": "reviewed"},
    )[1]
    assert seen["last_seen"] and seen["presence"] == "not_observed"
    ops.revoke("one")
    ops.rotate_device("one", "replacement" * 8)
    assert request(app, "/v1/identity/device", bearer="one" * 16)[0] == 401
    current = request(app, "/v1/identity/device", bearer="replacement" * 8)[1]
    assert current["device_id"] == "one" and current["last_seen"] == seen["last_seen"]
    assert ops.upload(upload["id"]) == before
    assert request(app, "/v1/identity/me", bearer=approved["session_token"])[0] == 200
    with pytest.raises(BoundaryError):
        ops.rotate_device("absent", "replacement" * 8)


def test_revocation_or_rotation_between_proof_and_approval_fails_closed(hub):
    app, token, _ = hub
    flow = create(app, existing=True)
    app.service.operations.rotate_device("one", "rotated" * 10)
    assert decision(app, token(), flow)[0] == 403
    assert poll(app, flow)[1] == {"status": "pending"}


def test_restart_can_redeliver_result_but_changed_master_key_cannot(hub):
    app, token, access = hub
    flow, approved = connected(hub)
    restarted = HubApplication(app.service, ADMIN, browser_access=access, public_origin=ORIGIN)
    assert poll(restarted, flow)[1] == approved
    changed = HubApplication(
        app.service, "changed" * 16, browser_access=access, public_origin=ORIGIN
    )
    assert poll(changed, flow)[1] == {"error": "identity_flow_key_changed"}
    # Already delivered sessions are separately hash-bound and retain their own expiry.
    assert request(changed, "/v1/identity/me", bearer=approved["session_token"])[0] == 200


def test_device_scope_filter_is_identical_for_browser_and_personal_reads(hub):
    app, token, _ = hub
    _, approved = connected(hub, existing=True)
    for device, identity in (("one", "a"), ("two", "b")):
        app.service.operations.create_upload(device, identity * 64, "c" * 64, {})
    for path, kwargs in (
        ("/app/api/collections", {"jwt": token()}),
        ("/v1/identity/console/collections", {"bearer": approved["session_token"]}),
    ):
        result = request(app, path, query="device=one&limit=25&offset=0", **kwargs)[1]
        assert result["total"] == 1 and result["items"][0]["device_id"] == "one"
        for query in ("device=elsewhere", "device=one&device=two", "device="):
            assert request(app, path, query=query, **kwargs)[0] == 403
        assert request(app, path, query="device=one&arbitrary=1", **kwargs)[0] == 400


def test_empty_scope_is_allowed_without_implicitly_granting_enrollment(hub):
    _, _, access = hub
    current = AccessVerifier(
        access.issuer,
        access.audience,
        [{"email": "new@example.org", "devices": [], "role": "collector"}],
    )
    value = current.member(current.issuer, "stable", "new@example.org")
    assert value.devices == () and value.enroll_devices is False
    assert value.subject != current.member(current.issuer, "other", "new@example.org").subject


def test_public_flow_bounds_ignore_forged_forwarded_ip_and_reject_callback(hub):
    app, _, _ = hub
    for index in range(20):
        result = request(
            app,
            "/v1/identity/flows",
            method="POST",
            body={
                "client_secret": SECRET,
                "device_name": "Mac",
            },
            headers={"HTTP_X_FORWARDED_FOR": f"10.0.0.{index}"},
        )
        assert result[0] == 201
    assert (
        request(
            app,
            "/v1/identity/flows",
            method="POST",
            body={
                "client_secret": SECRET,
                "device_name": "Mac",
            },
            headers={"HTTP_X_FORWARDED_FOR": "another"},
        )[0]
        == 429
    )
    for body in (
        {"client_secret": "short", "device_name": "Mac"},
        {"client_secret": SECRET, "device_name": "Mac", "callback": "https://evil.invalid"},
        {"client_secret": SECRET, "device_name": "x" * 10000},
    ):
        code, output = request(
            app, "/v1/identity/flows", method="POST", body=body, source="separate-source"
        )
        assert code in {400, 409} and SECRET not in json.dumps(output)


def test_schema2_migration_keeps_legacy_credentials_uploads_and_backup(tmp_path):
    path = tmp_path / "operations.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=2")
        db.execute(
            "CREATE TABLE devices(id TEXT PRIMARY KEY,token_hash TEXT UNIQUE,active INTEGER)"
        )
        db.execute("INSERT INTO devices VALUES(?,?,1)", ("legacy", token_hash("legacy" * 8)))
    ops = Operations(path)
    assert ops.authenticate("legacy" * 8) == "legacy"
    upload = ops.create_upload("legacy", "a" * 64, "b" * 64, {"legacy": True})
    before = ops.upload(upload["id"])
    snapshot = tmp_path / "backup.sqlite"
    ops.backup(snapshot)
    restored = Operations(snapshot)
    assert restored.authenticate("legacy" * 8) == "legacy"
    assert restored.upload(upload["id"]) == before
    with restored.transaction() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA == 3
        assert db.execute("SELECT owner_subject,last_seen FROM devices").fetchone()[:] == (
            None,
            None,
        )


def test_global_flow_capacity_is_fixed_and_expired_rows_are_reclaimable(hub):
    app, _, _ = hub
    flow = create(app)
    with app.service.operations.transaction() as db:
        for number in range(999):
            db.execute(
                "INSERT INTO identity_flows(id,client_hash,device_name,user_code,created_at,"
                "expires_at,status,key_id) VALUES(?,?,?,?,?,?,?,?)",
                (
                    f"{number:032x}",
                    "a" * 64,
                    "bounded",
                    "ABCDEF23",
                    time.time(),
                    time.time() + 600,
                    "pending",
                    app.identity.key_id,
                ),
            )
    code, result = request(
        app,
        "/v1/identity/flows",
        method="POST",
        body={
            "client_secret": SECRET,
            "device_name": "Mac",
        },
    )
    assert code == 429 and result["error"] == "identity_flow_capacity"
    with app.service.operations.transaction() as db:
        db.execute("UPDATE identity_flows SET expires_at=1 WHERE id!=?", (flow["flow_id"],))
    create(app)
    with app.service.operations.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM identity_flows").fetchone()[0] == 2


def test_missing_origin_disables_only_browser_writes_and_disabled_access_cannot_pair(hub):
    app, token, access = hub
    disabled = HubApplication(app.service, ADMIN)
    assert (
        request(
            disabled,
            "/v1/identity/flows",
            method="POST",
            body={
                "client_secret": SECRET,
                "device_name": "Mac",
            },
        )[0]
        == 503
    )
    assert request(disabled, "/v1/identity/device", bearer="one" * 16)[0] == 200
    no_origin = HubApplication(app.service, ADMIN, browser_access=access)
    flow = create(no_origin)
    assert decision(no_origin, token(), flow)[0] == 403
    assert request(no_origin, "/app/api/overview", jwt=token())[0] == 200
