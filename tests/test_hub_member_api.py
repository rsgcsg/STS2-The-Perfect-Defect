"""Actual membership/campaign/export services behind the transport-neutral member router."""

from __future__ import annotations

import concurrent.futures
import hashlib
import io
import json
from dataclasses import replace

import pytest
from platform_bundle3_fixture import bundle3, load, seal, write
from sts2_platform_evidence import DirectoryTransferManifest, verify_human_session_bundle
from test_campaign_onboarding import campaign as campaign
from test_hub_console import service
from test_hub_console import signed as signed

from stpd.artifact_contracts import Manifest
from stpd.collection_activity import CONSENT_FIELDS
from stpd.fullrun.platform_bundle3 import archive_bundle
from stpd.hub.campaigns import create_campaign_tables
from stpd.hub.console_auth import ConsolePrincipal
from stpd.hub.exports import REQUEST_SCHEMA
from stpd.hub.identity import IdentityService
from stpd.hub.member_api import MemberApi, grant_collection_sharing
from stpd.json_boundary import BoundaryError, json_bytes


@pytest.fixture
def api(campaign, signed, tmp_path):
    access, token, _ = signed
    owner = service(tmp_path / "hub")
    with owner.operations.transaction() as db:
        create_campaign_tables(db)
    identity = IdentityService(
        owner.operations, access, b"synthetic-only-key", "https://hub.example"
    )
    admin = identity.principal(access.authenticate(token()))
    member = identity.principal(access.authenticate(token(email="collector@example.org")))
    with owner.operations.transaction() as db:
        db.execute("UPDATE devices SET owner_subject=? WHERE id='one'", (member.subject,))
        db.execute("UPDATE devices SET owner_subject=? WHERE id='two'", (admin.subject,))
    router = MemberApi(owner, identity)
    template = router.admin_create_campaign(campaign[3], admin)
    return router, owner, admin, member, template


def enroll(api):
    router, _, _, member, template = api
    return router.write(
        "campaigns/" + template["template_id"] + "/enroll",
        {"device_id": "one", "consent": {key: True for key in CONSENT_FIELDS}},
        member,
    )


def staged(api, tmp_path):
    router, owner, _, _, _ = api
    enrollment = enroll(api)
    directory = bundle3(tmp_path / "bundle")
    path = directory / "session-bundle-manifest.json"
    manifest = load(path)
    manifest.update(worker_id="one", campaign_id=enrollment["campaign_id"])
    manifest["human_origin_attestation"]["worker_id"] = "one"
    write(path, manifest)
    seal(directory)
    bundle = verify_human_session_bundle(directory).require_value()
    transfer = DirectoryTransferManifest.from_directory(
        directory, content_id=bundle.bundle_content_id, artifact_type="human-session-bundle"
    )
    archive = archive_bundle(directory)
    intent = {
        "schema": "stpd/upload-intent-v1",
        "transfer_manifest": transfer.to_dict(),
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "archive_bytes": len(archive),
    }
    upload_id = owner.intent("one", intent)["upload_id"]
    owner.staging.write(upload_id, io.BytesIO(archive), len(archive))
    owner.operations.request_verification(upload_id)
    return upload_id, bundle, enrollment


def test_member_routes_owned_enrollment_and_exact_detail(api):
    router, _, admin, member, template = api
    listing = router.read("campaigns", "limit=1", member)
    assert listing["total"] == 1 and listing["templates"] == [template]
    enrollment = enroll(api)
    assert enroll(api) == enrollment
    own = router.read("campaigns/enrollments", "", member)
    assert own["items"] == [enrollment]
    exact = router.read("campaigns/enrollments/" + enrollment["enrollment_id"], "", member)
    assert exact == enrollment and exact["human_origin_verified"] is False
    assert router.read("campaigns/enrollments", "", admin)["items"] == []
    with pytest.raises(BoundaryError, match="enrollment_not_found"):
        router.read("campaigns/enrollments/" + enrollment["enrollment_id"], "", admin)
    with pytest.raises(BoundaryError, match="owned_active_device_required"):
        router.write(
            "campaigns/" + template["template_id"] + "/enroll",
            {"device_id": "two", "consent": {key: True for key in CONSENT_FIELDS}},
            member,
        )
    with pytest.raises(BoundaryError, match="missing_or_unknown_fields"):
        router.write(
            "campaigns/" + template["template_id"] + "/enroll",
            {"device_id": "one", "subject": admin.subject, "consent": {}},
            member,
        )


def test_admin_creation_separate_and_personal_session_cannot_admin(api):
    router, _, admin, member, template = api
    value = {**template["template"], "version": 2}
    with pytest.raises(BoundaryError, match="admin_browser_required"):
        router.admin_create_campaign(value, member)
    with pytest.raises(BoundaryError, match="admin_browser_required"):
        router.admin_create_campaign(value, replace(admin, session_binding=""))
    assert router.admin_create_campaign(value, admin)["template"]["version"] == 2
    with pytest.raises(BoundaryError, match="resource_not_found"):
        router.write("campaigns", value, admin)


def test_payload_export_and_stale_membership_rechecked(api):
    router, owner, admin, member, _ = api
    payload = owner.store.put_payload("weights", io.BytesIO(b"immutable weights"))
    manifest = Manifest("model", owner.producer, payloads=(payload,))
    owner.store.publish(manifest)
    owner.console_index.artifact(manifest)
    metadata = owner.console_index.artifacts(member, "models", limit=1, offset=0)["items"][0]
    assert metadata["payloads"] == [payload.to_dict()]
    selected = router.write(
        "exports",
        {
            "schema": REQUEST_SCHEMA,
            "collections": [],
            "artifacts": [{"artifact_id": manifest.artifact_id, "roles": ["weights"]}],
        },
        member,
    )
    personal = replace(member, session_binding="")
    assert router.read("exports/" + selected["export_id"], "", personal) == selected
    file = next(item for item in selected["files"] if item["role"] == "weights")
    info, stream = router.payload(selected["export_id"], file["file_id"], personal)
    assert hashlib.sha256(b"".join(stream)).hexdigest() == info["sha256"]
    router.identity.membership.update(admin, member.member_id, {"status": "disabled"})
    for call in (
        lambda: router.read("campaigns", "", member),
        lambda: router.read("exports/" + selected["export_id"], "", member),
        lambda: router.payload(selected["export_id"], file["file_id"], personal),
    ):
        with pytest.raises(BoundaryError, match="membership_not_authorized"):
            call()
    with pytest.raises(BoundaryError):
        router.read("campaigns", "", ConsolePrincipal("collector", ("one",)))


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        "status=verified",
        "url=https://evil.invalid",
        "limit=1&limit=2",
    ],
)
def test_member_pagination_is_bounded(api, query):
    router, _, _, member, _ = api
    with pytest.raises(BoundaryError):
        router.read("campaigns", query, member)


def test_receiver_automatically_grants_only_exact_verified_enrollment(api, tmp_path):
    router, owner, _, member, _ = api
    upload, bundle, enrollment = staged(api, tmp_path)
    assert owner.verify_pending() == 1
    row = owner.operations.upload(upload)
    receipt_before = row["receipt"]
    assert row["status"] == "verified"
    assert router.exports.collection_access([upload])[upload]["availability"] == "available"
    result = router.write(
        "exports", {"schema": REQUEST_SCHEMA, "collections": [upload], "artifacts": []}, member
    )
    assert result["files_count"] == 1 and result["files"][0]["role"] == "archive"
    with owner.operations.transaction() as db:
        events = db.execute(
            "SELECT detail FROM events WHERE operation='collection_sharing_associated' "
            "AND subject=?",
            (upload,),
        ).fetchall()
        assert len(events) == 1
        detail = json.loads(events[0][0])
        assert detail["human_origin_verified"] is False
        assert (
            detail["binding"]["enrollment_sha256"]
            == hashlib.sha256(json_bytes(enrollment)).hexdigest()
        )
        assert detail["evidence_ref"] == hashlib.sha256(json_bytes(detail["binding"])).hexdigest()
    # The same exact verified value is idempotent, including concurrent retries.
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: owner.associate_verified_bundle(upload, bundle), range(4)))
    assert owner.operations.upload(upload)["receipt"] == receipt_before
    grant_collection_sharing(
        owner, upload_id=upload, approved=False, evidence_ref="e" * 64, actor="owner"
    )
    assert owner.associate_verified_bundle(upload, bundle)["availability"] == "not_granted"
    assert router.exports.collection_access([upload])[upload]["availability"] == "not_granted"
    assert owner.operations.upload(upload)["receipt"] == receipt_before


def test_receiver_wrong_device_and_missing_enrollment_do_not_grant(api, tmp_path):
    router, owner, _, _, _ = api
    upload, bundle, _ = staged(api, tmp_path)
    # A valid archive claiming another enrolled device never borrows that consent.
    with owner.operations.transaction() as db:
        db.execute("UPDATE uploads SET device='two' WHERE id=?", (upload,))
    owner.verify_pending()
    assert owner.operations.upload(upload)["status"] == "verified"
    with owner.operations.transaction() as db:
        detail = db.execute(
            "SELECT detail FROM events WHERE operation='collection_sharing_unavailable' "
            "AND subject=?",
            (upload,),
        ).fetchone()[0]
        assert json.loads(detail)["reason"] == "verified_bundle_identity_mismatch"
    assert router.exports.collection_access([upload])[upload]["availability"] == "not_granted"
    with pytest.raises(BoundaryError, match="verified_bundle_identity_mismatch"):
        owner.associate_verified_bundle(upload, bundle)
    with owner.operations.transaction() as db:
        db.execute("UPDATE uploads SET device='one' WHERE id=?", (upload,))
        db.execute("DELETE FROM collection_enrollments")
    assert owner.associate_verified_bundle(upload, bundle)["reason"] == "enrollment_not_found"
    assert router.exports.collection_access([upload])[upload]["availability"] == "not_granted"
