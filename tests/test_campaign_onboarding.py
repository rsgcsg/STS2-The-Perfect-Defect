from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pytest
from sts2_platform_evidence.collection_tool import digest as tool_digest
from sts2_platform_evidence.delivery_config import DeliveryConfig

from stpd.collection_activity import CONSENT_FIELDS, validate_enrollment
from stpd.hub.campaigns import Campaigns, create_campaign_tables
from stpd.hub.console_auth import ConsolePrincipal
from stpd.hub.database import Operations
from stpd.json_boundary import BoundaryError
from stpd.workbench.campaign_prepare import prepare_campaign
from stpd.workbench.developer import ProjectConfig, atomic_json


class CurrentMembership:
    """Contract spy: production caller supplies the Hub MembershipService, not this fixture."""

    def __init__(self):
        self.active = True
        self.calls = []

    def authorize(self, db, principal):
        assert db.in_transaction
        self.calls.append("authorize")
        if not self.active or principal.role not in {"member", "admin"}:
            raise BoundaryError("membership", "active_member_required")
        return principal

    def admin(self, db, principal):
        current = self.authorize(db, principal)
        if current.role != "admin":
            raise BoundaryError("membership", "admin_required")
        return current


@pytest.fixture
def campaign(tmp_path):
    ops = Operations(tmp_path / "operations.sqlite")
    with ops.transaction() as db:
        create_campaign_tables(db)
    authority = CurrentMembership()
    admin = ConsolePrincipal("admin", (), subject="admin")
    member = ConsolePrincipal("member", ("computer",), subject="member")
    ops.register("computer", "x" * 40)
    with ops.transaction() as db:
        db.execute("UPDATE devices SET owner_subject='member' WHERE id='computer'")
    tool = tmp_path / "tool"
    tool.mkdir()
    for name in ["platform-bom.json", "sts2-human-annotator.dll"]:
        (tool / name).write_bytes(b"explicitly synthetic tool bytes")
    identity = {
        "source_revision": "1" * 40,
        "worktree": "clean",
        "entrypoint": "sts2-human-annotator.dll",
        "supported_recording_schema": "sts2.human-annotator/recording-manifest-2",
        "files": [
            {
                "path": p.name,
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in sorted(tool.iterdir())
        ],
    }
    pin = tool_digest(identity)
    (tool / "collection-tool.json").write_text(
        json.dumps(
            {
                "schema": "sts2.evidence/collection-tool-1",
                "release_id": pin,
                "identity": identity,
            }
        )
    )
    template = {
        "schema": "stpd/collection-activity-v1",
        "activity_id": "synthetic-test",
        "version": 1,
        "name": "Synthetic activity",
        "description": "Engineering fixture only",
        "consent_text": "I declare Human origin and authorize upload and project-member sharing.",
        "platform_source_revision": "a" * 40,
        "evidence_source_revision": "b" * 40,
        "tool_release_id": pin,
        "game": {"version": "synthetic", "revision": "fixture", "assembly_sha256": "c" * 64},
        "mod": {"sha256": "d" * 64, "mvid": "00000000-0000-0000-0000-000000000001"},
        "allowed_upload_hosts": ["storage.example.invalid"],
        "sharing_scope": "project_members",
    }
    state = tmp_path / "state"
    state.mkdir()
    config = ProjectConfig(
        state,
        "https://hub.example.invalid",
        "",
        None,
        {
            "platform_source_revision": "a" * 40,
            "evidence_source_revision": "b" * 40,
        },
    )
    atomic_json(
        state / "device.json",
        {
            "hub_url": config.hub_url,
            "device_id": "computer",
            "token": "x" * 40,
        },
    )
    return Campaigns(ops, authority), admin, member, template, config, tool


def enroll(campaign):
    service, admin, member, template, *_ = campaign
    published = service.create(admin, template)
    return service.enroll(
        member, published["template_id"], "computer", {key: True for key in CONSENT_FIELDS}
    )


def test_template_admin_immutable_versioned_and_bounded_listing(campaign):
    service, admin, member, template, *_ = campaign
    with pytest.raises(BoundaryError, match="admin_required"):
        service.create(member, template)
    one = service.create(admin, template)
    assert service.create(admin, template) == one
    with pytest.raises(BoundaryError, match="immutable_template_conflict"):
        service.create(admin, {**template, "name": "changed"})
    two = service.create(admin, {**template, "version": 2})
    assert two["template_id"] != one["template_id"]
    with pytest.raises(BoundaryError, match="next_template_version_required"):
        service.create(admin, {**template, "version": 4})
    page = service.list(member, limit=1)
    assert page["total"] == 2 and page["next_offset"] == 1
    assert service.list(member, limit=1, offset=1)["next_offset"] is None
    template["name"] = "caller mutation"
    assert service.list(member)["templates"][0]["template"]["name"] != "caller mutation"


@pytest.mark.parametrize("field", sorted(CONSENT_FIELDS))
@pytest.mark.parametrize("value", [False, "true", 1])
def test_only_explicit_three_part_consent_can_enroll(campaign, field, value):
    service, admin, member, template, *_ = campaign
    published = service.create(admin, template)
    consent = {key: True for key in CONSENT_FIELDS}
    consent[field] = value
    with pytest.raises(BoundaryError, match="explicit_campaign_consent_required"):
        service.enroll(member, published["template_id"], "computer", consent)
    with service.ops.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM collection_enrollments").fetchone()[0] == 0


def test_enrollment_same_owner_device_idempotency_and_live_auth_contract(campaign):
    service, admin, member, template, *_ = campaign
    result = enroll(campaign)
    assert enroll(campaign) == result
    assert result["human_origin_verified"] is False
    assert result["campaign_id"] == "campaign-" + result["enrollment_id"]
    assert validate_enrollment(result) == result
    with service.ops.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM collection_enrollments").fetchone()[0] == 1
        db.execute("UPDATE devices SET active=0")
    with pytest.raises(BoundaryError, match="owned_active_device_required"):
        enroll(campaign)
    service.members.active = False
    for operation in [
        lambda: service.list(member),
        lambda: service.create(admin, template),
        lambda: enroll(campaign),
    ]:
        with pytest.raises(BoundaryError, match="active_member_required"):
            operation()


def test_shared_scope_is_not_device_ownership(campaign):
    service, admin, _, template, *_ = campaign
    selected = service.create(admin, template)
    other = ConsolePrincipal("member", ("computer",), subject="not-owner")
    with pytest.raises(BoundaryError, match="owned_active_device_required"):
        service.enroll(
            other, selected["template_id"], "computer", {key: True for key in CONSENT_FIELDS}
        )


def test_fresh_preparation_preserves_history_credentials_and_active_config(campaign, tmp_path):
    result = enroll(campaign)
    _, _, _, _, config, tool = campaign
    historical = tmp_path / "historical-recordings"
    historical.mkdir()
    (historical / "sealed-session.json").write_text("must not enroll this")
    original_device = (config.state_dir / "device.json").read_bytes()
    prepared = prepare_campaign(config, result, tool)
    assert prepared["status"] == "native_binding_required"
    assert prepared["native_binding_verified"] is False and prepared["delivery_started"] is False
    assert config.delivery_config is None
    assert (config.state_dir / "device.json").read_bytes() == original_device
    assert (historical / "sealed-session.json").read_text() == "must not enroll this"
    actual = DeliveryConfig.load(Path(prepared["delivery_config"]))
    assert actual.campaign_id == result["campaign_id"]
    assert actual.worker_id == "computer" and actual.human_origin_attested is True
    assert list(actual.recordings_root.iterdir()) == [] and list(actual.outbox_root.iterdir()) == []
    if os.name != "nt":
        assert Path(prepared["delivery_config"]).stat().st_mode & 0o077 == 0
    # Reopening preparation neither scans nor deletes future native data in the dedicated root.
    (actual.recordings_root / "untouched.txt").write_text("retained")
    assert prepare_campaign(config, result, tool) == prepared
    assert (actual.recordings_root / "untouched.txt").read_text() == "retained"


def test_prepare_rejects_remote_and_local_identity_drift_before_creating_roots(campaign):
    selected = enroll(campaign)
    _, _, _, _, config, tool = campaign
    for changed in [
        {**selected, "human_origin_verified": True},
        {**selected, "enrollment_id": "../unsafe"},
        {**selected, "device_id": "other-computer"},
    ]:
        with pytest.raises(ValueError):
            prepare_campaign(config, changed, tool)
    (tool / "sts2-human-annotator.dll").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        prepare_campaign(config, selected, tool)
    assert not (config.state_dir / "campaigns").exists()


def test_incomplete_publication_remains_fail_closed_without_recreating_history(
    campaign, monkeypatch
):
    selected = enroll(campaign)
    _, _, _, _, config, tool = campaign
    import stpd.workbench.campaign_prepare as module

    write = module.atomic_json

    def interrupted(path, value):
        if path.name == "preparation.json":
            raise OSError("synthetic interruption")
        write(path, value)

    monkeypatch.setattr(module, "atomic_json", interrupted)
    with pytest.raises(OSError):
        prepare_campaign(config, selected, tool)
    monkeypatch.setattr(module, "atomic_json", write)
    with pytest.raises(BoundaryError, match="preparation_exists_or_incomplete"):
        prepare_campaign(config, selected, tool)
    assert config.delivery_config is None
    assert len(list((config.state_dir / "campaigns").iterdir())) == 1


def test_symlinked_campaign_root_is_not_followed(campaign, tmp_path):
    selected = enroll(campaign)
    _, _, _, _, config, tool = campaign
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (config.state_dir / "campaigns").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create symlinks")
    with pytest.raises(BoundaryError, match="non_symlink_directory_required"):
        prepare_campaign(config, selected, tool)
    assert list(outside.iterdir()) == []


def test_template_rejects_unversioned_or_private_fields(campaign):
    service, admin, _, template, *_ = campaign
    for change in [
        {"version": True},
        {"version": 0},
        {"allowed_upload_hosts": ["https://bad/"]},
        {"token": "private"},
        {"recordings_root": "/some/path"},
    ]:
        with pytest.raises(ValueError):
            service.create(admin, {**template, **change})
    future = {**enroll(campaign), "declared_at": time.time(), "consent": {}}
    with pytest.raises(ValueError):
        validate_enrollment(future)
