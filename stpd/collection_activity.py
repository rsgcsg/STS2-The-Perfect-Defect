"""Versioned activity and consent data shared by Hub and local preparation."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from .json_boundary import BoundaryError, decode_json, digest, json_bytes, object_fields, text

TEMPLATE_SCHEMA = "stpd/collection-activity-v1"
ENROLLMENT_SCHEMA = "stpd/collection-enrollment-v1"
CONSENT_FIELDS = {"human_origin_attested", "upload_authorized", "project_sharing_authorized"}


def validate_template(value: object) -> dict[str, Any]:
    obj = object_fields(
        value,
        {
            "schema",
            "activity_id",
            "version",
            "name",
            "description",
            "consent_text",
            "platform_source_revision",
            "evidence_source_revision",
            "tool_release_id",
            "game",
            "mod",
            "allowed_upload_hosts",
            "sharing_scope",
        },
        "campaign.template",
    )
    if obj["schema"] != TEMPLATE_SCHEMA or obj["sharing_scope"] != "project_members":
        raise BoundaryError("campaign", "unsupported_template")
    slug = text(obj["activity_id"], "campaign.activity_id", maximum=80)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", slug):
        raise BoundaryError("campaign", "invalid_activity_id")
    if type(obj["version"]) is not int or not 1 <= obj["version"] <= 10000:
        raise BoundaryError("campaign", "invalid_template_version")
    for key, maximum in (("name", 120), ("description", 2000), ("consent_text", 2000)):
        text(obj[key], "campaign." + key, maximum=maximum)
    for key in ("platform_source_revision", "evidence_source_revision"):
        digest(obj[key], "campaign." + key, length=40)
    digest(obj["tool_release_id"], "campaign.tool_release_id")
    game = object_fields(obj["game"], {"version", "revision", "assembly_sha256"}, "campaign.game")
    text(game["version"], "campaign.game.version", maximum=80)
    text(game["revision"], "campaign.game.revision", maximum=80)
    digest(game["assembly_sha256"], "campaign.game.assembly")
    mod = object_fields(obj["mod"], {"sha256", "mvid"}, "campaign.mod")
    digest(mod["sha256"], "campaign.mod.sha256")
    if not isinstance(mod["mvid"], str) or not re.fullmatch(
        r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", mod["mvid"]
    ):
        raise BoundaryError("campaign", "invalid_mod_mvid")
    hosts = obj["allowed_upload_hosts"]
    if (
        not isinstance(hosts, list)
        or not 1 <= len(hosts) <= 8
        or any(
            not isinstance(h, str)
            or len(h) > 253
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", h)
            for h in hosts
        )
        or len(set(hosts)) != len(hosts)
    ):
        raise BoundaryError("campaign", "invalid_upload_hosts")
    # Own a canonical copy; callers cannot mutate the persisted identity after validation.
    result: dict[str, Any] = decode_json(json_bytes(obj))
    return result


def validate_consent(value: object) -> dict[str, bool]:
    obj = object_fields(value, CONSENT_FIELDS, "campaign.consent")
    if any(obj[key] is not True for key in CONSENT_FIELDS):
        raise BoundaryError("campaign", "explicit_campaign_consent_required")
    return {key: True for key in sorted(CONSENT_FIELDS)}


def validate_enrollment(value: object) -> dict[str, Any]:
    obj = object_fields(
        value,
        {
            "schema",
            "enrollment_id",
            "device_id",
            "template_id",
            "template",
            "consent",
            "declared_at",
            "campaign_id",
            "human_origin_verified",
        },
        "campaign.enrollment",
    )
    if obj["schema"] != ENROLLMENT_SCHEMA or obj["human_origin_verified"] is not False:
        raise BoundaryError("campaign", "unsupported_enrollment")
    identity = digest(obj["enrollment_id"], "campaign.enrollment_id", length=32)
    text(obj["device_id"], "campaign.device_id", maximum=128)
    template = validate_template(obj["template"])
    if (
        obj["template_id"] != hashlib.sha256(json_bytes(template)).hexdigest()
        or obj["campaign_id"] != "campaign-" + identity
    ):
        raise BoundaryError("campaign", "enrollment_identity_mismatch")
    validate_consent(obj["consent"])
    when = obj["declared_at"]
    if type(when) not in (int, float) or not math.isfinite(when) or when <= 0:
        raise BoundaryError("campaign", "invalid_declaration_time")
    result: dict[str, Any] = decode_json(json_bytes(obj))
    return result
