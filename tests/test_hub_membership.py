"""Dynamic Hub membership, atomic revocation, and explicit legacy migration."""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import replace

import pytest
from test_hub_console import ISSUER
from test_hub_console import signed as signed

from stpd.hub.database import CURRENT_SCHEMA, Operations, token_hash
from stpd.hub.identity import IdentityService
from stpd.hub.membership import MembershipService
from stpd.json_boundary import BoundaryError


@pytest.fixture
def membership(tmp_path, signed):
    access, token, _ = signed
    ops = Operations(tmp_path / "ops.sqlite")
    identity = IdentityService(ops, access, b"test-identity-key", "https://hub.example")
    identity.membership.bootstrap(issuer=ISSUER, admin_email="owner@example.org")
    admin = identity.principal(access.authenticate(token()))
    return identity, ops, admin, access, token


def invite_member(membership, *, email="member@example.org", role="member"):
    identity, _, admin, access, token = membership
    row = identity.membership.invite(admin, {"email": email, "role": role})
    principal = identity.principal(access.authenticate(token(email=email, sub=email)))
    assert principal.member_id == row["member_id"]
    return principal


def connect(identity, principal, *, existing=None):
    body = {"client_secret": "s" * 40, "device_name": "test computer"}
    if existing:
        body.update(device_id=existing[0], device_token=existing[1])
    flow = identity.create(body)
    csrf = identity.me(principal, browser=True)["csrf_token"]
    identity.check_browser_write(principal, "https://hub.example", csrf)
    identity.decide(
        flow["flow_id"], {"csrf_token": csrf, "user_code": flow["user_code"]}, principal, deny=False
    )
    return flow, identity.poll(flow["flow_id"], {"client_secret": "s" * 40})


def test_no_implicit_bootstrap_and_identity_is_not_membership(tmp_path, signed):
    access, token, _ = signed
    identity = IdentityService(Operations(tmp_path / "ops"), access, b"key")
    signed_identity = access.authenticate(token())
    assert signed_identity.role == "authenticated" and not signed_identity.research
    with pytest.raises(BoundaryError, match="not_initialized"):
        identity.principal(signed_identity)
    with identity.ops.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM identity_members").fetchone()[0] == 0
    identity.membership.bootstrap(issuer=ISSUER, admin_email="different@example.org")
    with pytest.raises(BoundaryError, match="not_authorized"):
        identity.principal(signed_identity)
    with pytest.raises(BoundaryError, match="already_initialized"):
        identity.membership.bootstrap(issuer=ISSUER, admin_email="owner@example.org")


def test_invite_binds_signed_subject_once_and_defaults_are_bounded(membership):
    identity, _, admin, access, token = membership
    invited = identity.membership.invite(admin, {"email": "Member@Example.org"})
    assert invited["status"] == "invited" and invited["device_quota"] == 3
    assert invited["enroll_devices"] is True
    with pytest.raises(BoundaryError, match="not_authorized"):
        identity.principal(access.authenticate(token(email="other@example.org", sub="first")))
    member = identity.principal(access.authenticate(token(email="member@example.org", sub="first")))
    assert member.member_id == invited["member_id"] and member.role == "member"
    assert member.project_shared and member.research and member.owned_devices == ()
    with pytest.raises(BoundaryError, match="not_authorized"):
        identity.principal(access.authenticate(token(email="member@example.org", sub="second")))
    # A bound provider subject survives an email change; the email cannot rebind its owner.
    assert (
        identity.principal(
            access.authenticate(token(email="renamed@example.org", sub="first"))
        ).subject
        == member.subject
    )
    with pytest.raises(BoundaryError, match="already_exists"):
        identity.membership.invite(admin, {"email": "MEMBER@example.org"})


def test_disabled_invite_reenable_does_not_activate_without_signed_login(membership):
    identity, _, admin, access, token = membership
    row = identity.membership.invite(admin, {"email": "new@example.org"})
    identity.membership.update(admin, row["member_id"], {"status": "disabled"})
    with pytest.raises(BoundaryError, match="not_authorized"):
        identity.principal(access.authenticate(token(email="new@example.org", sub="new")))
    result = identity.membership.update(admin, row["member_id"], {"status": "active"})
    assert result["status"] == "invited" and result["subject"] is None
    assert (
        identity.principal(
            access.authenticate(token(email="new@example.org", sub="new"))
        ).membership_status
        == "active"
    )


def test_last_active_admin_cannot_be_removed_even_with_pending_admin_invite(membership):
    identity, _, admin, _, _ = membership
    identity.membership.invite(admin, {"email": "future-admin@example.org", "role": "admin"})
    for value in ({"role": "member"}, {"status": "disabled"}):
        with pytest.raises(BoundaryError, match="last_admin_required"):
            identity.membership.update(admin, admin.member_id, value)
    assert identity.membership.list(admin)["total"] == 2


def test_concurrent_admin_demotions_keep_one_active_admin(membership):
    identity, ops, admin, _, _ = membership
    second = invite_member(membership, role="admin")

    def demote(principal):
        try:
            identity.membership.update(principal, principal.member_id, {"role": "member"})
            return "changed"
        except BoundaryError as error:
            return error.code

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        results = list(pool.map(demote, (admin, second)))
    assert sorted(results) == ["changed", "last_admin_required"]
    with ops.transaction() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM identity_members WHERE role='admin' AND status='active'"
            ).fetchone()[0]
            == 1
        )


def test_revocation_is_atomic_across_browser_personal_device_and_pending_delivery(membership):
    identity, ops, admin, _, _ = membership
    member = invite_member(membership)
    flow, result = connect(identity, member)
    device, personal = result["device"], result["session_token"]
    upload = ops.create_upload(device["device_id"], "a" * 64, "b" * 64, {"evidence": "unchanged"})
    before = ops.upload(upload["id"])
    identity.membership.update(admin, member.member_id, {"status": "disabled"})
    for action in (
        lambda: identity.principal(member),
        lambda: identity.personal(personal),
        lambda: ops.authenticate(device["token"]),
        lambda: identity.device(device["token"]),
        lambda: ops.rotate_device(device["device_id"], "r" * 40),
    ):
        with pytest.raises(BoundaryError):
            action()
    assert identity.poll(flow["flow_id"], {"client_secret": "s" * 40}) == {"status": "denied"}
    assert ops.upload(upload["id"]) == before
    identity.membership.update(admin, member.member_id, {"status": "active"})
    assert identity.principal(member).subject == member.subject
    for action in (lambda: identity.personal(personal), lambda: ops.authenticate(device["token"])):
        with pytest.raises(BoundaryError):
            action()
    ops.rotate_device(device["device_id"], "r" * 40)
    assert ops.authenticate("r" * 40) == device["device_id"]
    assert ops.upload(upload["id"]) == before


def test_owner_membership_checked_even_if_device_active_bit_was_not_revoked(membership):
    identity, ops, _, _, _ = membership
    member = invite_member(membership)
    _, result = connect(identity, member)
    with ops.transaction() as db:
        db.execute("UPDATE identity_members SET status='disabled' WHERE id=?", (member.member_id,))
        assert not ops.device_authorized(db, result["device"]["device_id"])
    with pytest.raises(BoundaryError, match="unauthorized"):
        ops.authenticate(result["device"]["token"])
    with pytest.raises(BoundaryError, match="unauthorized"):
        identity.device(result["device"]["token"], heartbeat=True)


def test_membership_write_failure_rolls_back_revocation_and_audit(membership, monkeypatch):
    identity, ops, admin, _, _ = membership
    member = invite_member(membership)
    _, result = connect(identity, member)
    with monkeypatch.context() as patch:
        patch.setattr(
            ops, "_event", lambda *args: (_ for _ in ()).throw(OSError("audit unavailable"))
        )
        with pytest.raises(OSError):
            identity.membership.update(admin, member.member_id, {"status": "disabled"})
    assert identity.personal(result["session_token"]).subject == member.subject
    assert ops.authenticate(result["device"]["token"]) == result["device"]["device_id"]


def test_personal_admin_cannot_write_or_borrow_browser_admin_claims(membership):
    identity, _, admin, _, _ = membership
    member = invite_member(membership)
    _, result = connect(identity, admin)
    personal = identity.personal(result["session_token"])
    for principal in (personal, replace(member, role="admin"), replace(admin, expires_at=1)):
        for action in (
            lambda principal=principal: identity.membership.invite(
                principal, {"email": "no@example.org"}
            ),
            lambda principal=principal: identity.membership.update(
                principal, member.member_id, {"role": "admin"}
            ),
            lambda principal=principal: identity.membership.revoke_device(
                principal, result["device"]["device_id"]
            ),
        ):
            with pytest.raises(BoundaryError):
                action()


def test_quota_enrollment_and_control_are_independent_from_project_visibility(membership):
    identity, ops, admin, _, _ = membership
    member = invite_member(membership)
    identity.membership.update(admin, member.member_id, {"device_quota": 1})
    _, grant = connect(identity, member)
    _, other_grant = connect(identity, admin)
    before = identity.me(member)
    assert len(before["devices"]) == 2
    assert before["principal"]["owned_device_ids"] == [grant["device"]["device_id"]]
    with pytest.raises(BoundaryError, match="not_authorized"):
        connect(identity, member)
    with pytest.raises(BoundaryError, match="not_authorized"):
        connect(
            identity,
            member,
            existing=(other_grant["device"]["device_id"], other_grant["device"]["token"]),
        )
    with pytest.raises(BoundaryError, match="not_authorized"):
        identity.membership.revoke_device(member, other_grant["device"]["device_id"])
    scoped, query = identity.scoped_query(
        member, "device=" + other_grant["device"]["device_id"] + "&limit=25"
    )
    assert scoped.data_device == other_grant["device"]["device_id"] and query == "limit=25"
    assert scoped.owned_devices == (grant["device"]["device_id"],)
    identity.membership.revoke_device(member, grant["device"]["device_id"])
    _, replacement = connect(identity, member)
    assert replacement["device"]["device_id"] != grant["device"]["device_id"]
    assert ops.authenticate(replacement["device"]["token"]) == replacement["device"]["device_id"]


def test_legacy_schema3_explicit_import_preserves_identity_and_never_elevates_operator(
    tmp_path, signed
):
    access, token, _ = signed
    ops = Operations(tmp_path / "old.sqlite")
    old = access.authenticate(token())
    now = time.time()
    personal = "stpd_personal_" + "c" * 64
    with ops.transaction() as db:
        db.execute(
            "INSERT INTO identity_users VALUES(?,?,?,?)",
            (old.subject, old.issuer, old.access_subject, old.email),
        )
        db.execute(
            "INSERT INTO devices(id,token_hash,active,owner_subject) VALUES(?,?,1,?)",
            ("old-device", token_hash("old" * 20), old.subject),
        )
        db.execute(
            "INSERT INTO identity_sessions VALUES(?,?,?,?)",
            (token_hash(personal), old.subject, now + 60, now),
        )
        db.execute("DROP TABLE identity_members")
        db.execute("DROP TABLE identity_claim_scopes")
        db.execute("PRAGMA user_version=3")
    restored = Operations(ops.path)
    before = restored.create_upload("old-device", "a" * 64, "b" * 64, {"old": "intent"})
    members = MembershipService(restored)
    members.bootstrap(
        issuer=ISSUER,
        admin_email="new-admin@example.org",
        legacy_principals=[
            {
                "email": old.email,
                "subject": old.access_subject,
                "role": "operator",
                "devices": ["old-device"],
                "enroll_devices": True,
            }
        ],
    )
    identity = IdentityService(restored, access, b"key")
    current = identity.personal(personal)
    assert current.role == "member" and current.subject == old.subject
    assert restored.authenticate("old" * 20) == "old-device"
    assert restored.upload(before["id"])["intent"] == '{"old":"intent"}'
    with restored.transaction() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA == 4
        assert db.execute("SELECT token_hash,owner_subject FROM devices").fetchone()[:] == (
            token_hash("old" * 20),
            old.subject,
        )
    snapshot = tmp_path / "backup.sqlite"
    restored.backup(snapshot)
    recovered = IdentityService(Operations(snapshot), access, b"key")
    assert recovered.personal(personal).subject == old.subject
    assert recovered.device("old" * 20)["device_id"] == "old-device"
    assert recovered.ops.upload(before["id"]) == restored.upload(before["id"])


@pytest.mark.parametrize(
    "value",
    [
        {"role": "operator"},
        {"device_quota": -1},
        {"device_quota": True},
        {"device_quota": 129},
        {"enroll_devices": 1},
        {"status": "invited"},
        {"unknown": 1},
        {},
    ],
)
def test_admin_settings_reject_invalid_fields(membership, value):
    identity, _, admin, _, _ = membership
    with pytest.raises(BoundaryError, match="invalid_member_request"):
        identity.membership.update(admin, admin.member_id, value)
