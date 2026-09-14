"""Prepare an explicitly consented campaign without changing or starting the game or delivery."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from sts2_platform_evidence.collection_tool import CollectionTool
from sts2_platform_evidence.delivery_config import DeliveryConfig

from ..collection_activity import validate_enrollment
from ..json_boundary import BoundaryError, json_bytes
from .developer import ProjectConfig, atomic_json
from .identity import LocalIdentity, private_read


def _directory(path: Path) -> None:
    if path.is_symlink():
        raise BoundaryError("campaign", "non_symlink_directory_required")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise BoundaryError("campaign", "directory_required")


def prepare_campaign(
    config: ProjectConfig, enrollment: object, tool_directory: Path
) -> dict[str, Any]:
    """Caller obtains enrollment through the authenticated Hub; no browser paths are imported.

    This produces inactive configuration only. The application must keep native-root binding,
    exact loaded identity and owning delivery doctor as separate checks before activation.
    """
    selected = validate_enrollment(enrollment)
    device = LocalIdentity(config).device()
    if device.get("device_id") != selected["device_id"] or not device.get("token"):
        raise BoundaryError("campaign", "matching_local_device_required")
    template = selected["template"]
    if any(
        config.combination.get(key) != template[key]
        for key in ("platform_source_revision", "evidence_source_revision")
    ):
        raise BoundaryError("campaign", "approved_combination_required")
    if not config.hub_url.startswith("https://"):
        raise BoundaryError("campaign", "https_hub_required")
    if not tool_directory.is_absolute() or tool_directory.is_symlink():
        raise BoundaryError("campaign", "absolute_non_symlink_tool_required")
    owner = CollectionTool(tool_directory, template["tool_release_id"])
    _directory(config.state_dir)
    campaigns = config.state_dir / "campaigns"
    _directory(campaigns)
    directory = campaigns / selected["enrollment_id"]
    delivery_path = directory / "delivery.json"
    record_path = directory / "preparation.json"
    expected = {
        "schema": "stpd/local-campaign-preparation-v1",
        "enrollment": selected,
        "enrollment_sha256": hashlib.sha256(json_bytes(selected)).hexdigest(),
        "hub_url": config.hub_url,
        "tool_directory": str(tool_directory.resolve()),
        "delivery_config": str(delivery_path),
        "recordings_root": str(directory / "recordings"),
        "outbox_root": str(directory / "outbox"),
        "status": "native_binding_required",
        "native_binding_verified": False,
        "delivery_started": False,
        "required_native_identity": {"game": template["game"], "mod": template["mod"]},
    }
    if directory.exists() or directory.is_symlink():
        if directory.is_symlink() or private_read(record_path) != expected:
            raise BoundaryError("campaign", "preparation_exists_or_incomplete")
        observed = DeliveryConfig.load(delivery_path)
        if observed != _delivery(expected, template, selected):
            raise BoundaryError("campaign", "prepared_config_changed")
        return expected
    os.mkdir(directory, mode=0o700)
    # Each root is created exclusively. No discovery, copy or enrollment of older recordings.
    os.mkdir(directory / "recordings", mode=0o700)
    os.mkdir(directory / "outbox", mode=0o700)
    cfg = _delivery(expected, template, selected)
    atomic_json(
        delivery_path,
        {
            "schema": "sts2.evidence/delivery-config-1",
            "recordings_root": str(cfg.recordings_root),
            "outbox_root": str(cfg.outbox_root),
            "tool_directory": str(cfg.tool_directory),
            "tool_release_id": cfg.tool_release_id,
            "worker_id": cfg.worker_id,
            "campaign_id": cfg.campaign_id,
            "human_origin_attested": cfg.human_origin_attested,
            "hub_url": cfg.hub_url,
            "allowed_upload_hosts": cfg.allowed_upload_hosts,
        },
    )
    # The Platform codec, not this preparation layer, owns actual delivery config admission.
    if DeliveryConfig.load(delivery_path) != cfg or owner.verify() != owner.manifest:
        raise BoundaryError("campaign", "prepared_owner_identity_changed")
    atomic_json(record_path, expected)
    return expected


def _delivery(
    prepared: dict[str, Any], template: dict[str, Any], selected: dict[str, Any]
) -> DeliveryConfig:
    return DeliveryConfig(
        recordings_root=Path(prepared["recordings_root"]),
        outbox_root=Path(prepared["outbox_root"]),
        tool_directory=Path(prepared["tool_directory"]),
        tool_release_id=template["tool_release_id"],
        worker_id=selected["device_id"],
        campaign_id=selected["campaign_id"],
        human_origin_attested=selected["consent"]["human_origin_attested"],
        hub_url=prepared["hub_url"],
        allowed_upload_hosts=template["allowed_upload_hosts"],
    )
