"""Constant-cost filesystem observations, not health, admission or cleanup authority.

This file deliberately uses only the standard library: host preflight loads this exact
source file without importing the research package or requiring its Python environment.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "stpd/filesystem-capacity-v1"
# One verifier retains the compressed archive, expanded tar and extracted files together.
# uploads.py bounds those at 512 MiB + 2 GiB + 2 GiB. backup.py allows a 512 MiB
# snapshot; 1 GiB remains for the operating system and incidental writes. This is an
# operational reserve, not a quota or a promise for concurrent operator bulk work.
RESERVE_BYTES = 6 * 1024**3
RESERVE_INODES = 100_000  # Operational floor, not an upper bound for arbitrary nested paths.
IMAGE_RESERVE_BYTES = 1024**3
IMAGE_RESERVE_INODES = 10_000


def nonnegative(value: object) -> bool:
    return type(value) is int and value >= 0


def filesystem_capacity(
    path: Path,
    *,
    additional_bytes: int = 0,
    additional_inodes: int = 0,
    reserve_bytes: int = RESERVE_BYTES,
    reserve_inodes: int = RESERVE_INODES,
) -> dict[str, Any]:
    """Use bytes available to this UID; unknown inode support never means zero usage."""
    if any(not nonnegative(value) for value in (
        additional_bytes, additional_inodes, reserve_bytes, reserve_inodes,
    )):
        raise ValueError("invalid_capacity_requirement")
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "status": "unknown",
        "total_bytes": None,
        "free_bytes": None,
        "used_bytes": None,
        "used_percent": None,
        "total_inodes": None,
        "free_inodes": None,
        "used_inode_percent": None,
        "reserve_bytes": reserve_bytes,
        "reserve_inodes": reserve_inodes,
        "additional_bytes": additional_bytes,
        "additional_inodes": additional_inodes,
        "required_free_bytes": reserve_bytes + additional_bytes,
        "required_free_inodes": reserve_inodes + additional_inodes,
        "reasons": [],
        "scope": "observed_filesystem_only",
        "automatic_cleanup": False,
    }
    try:
        if not path.is_dir() or path.is_symlink():
            raise OSError
        disk = shutil.disk_usage(path)
        result.update(
            total_bytes=disk.total, free_bytes=disk.free, used_bytes=disk.used,
            used_percent=round(disk.used * 100 / disk.total, 1) if disk.total else None,
        )
        if disk.free < result["required_free_bytes"]:
            result["reasons"].append("free_bytes_below_reserve")
        statvfs = getattr(os, "statvfs", None)
        info = statvfs(path) if statvfs is not None else None
        if info is not None and info.f_files > 0 and info.f_favail >= 0:
            result.update(
                total_inodes=info.f_files, free_inodes=info.f_favail,
                used_inode_percent=round((info.f_files - info.f_ffree) * 100 / info.f_files, 1),
            )
            if info.f_favail < result["required_free_inodes"]:
                result["reasons"].append("free_inodes_below_reserve")
        else:
            result["reasons"].append("inode_capacity_unavailable")
        result["status"] = (
            "attention" if any(reason.startswith("free_") for reason in result["reasons"])
            else "unknown" if result["reasons"] else "ok"
        )
    except OSError:
        result["reasons"].append("filesystem_observation_unavailable")
    return result


def host_capacity(
    state: Path,
    image_store: Path,
    *,
    additional_bytes: int,
    additional_inodes: int,
) -> dict[str, Any]:
    """Measure actual filesystems; shared devices count the operational reserve once.

    Additional allocation is explicit peak image pull/unpack or other reviewed work.
    Reclaimable Docker accounting is not free disk. Existing current/rollback images
    remain allocated and are never proposed for deletion by this observer.
    """
    try:
        if any(not path.is_dir() or path.is_symlink() for path in (state, image_store)):
            raise OSError
        shared = state.stat().st_dev == image_store.stat().st_dev
    except OSError:
        shared = None
    state_report = filesystem_capacity(
        state, additional_bytes=additional_bytes if shared else 0,
        additional_inodes=additional_inodes if shared else 0,
    )
    state_report["scope"] = "application_state_and_image_store" if shared else "application_state"
    reports = [state_report]
    if not shared:
        image_report = filesystem_capacity(
            image_store, additional_bytes=additional_bytes, additional_inodes=additional_inodes,
            reserve_bytes=IMAGE_RESERVE_BYTES, reserve_inodes=IMAGE_RESERVE_INODES,
        )
        image_report["scope"] = "image_store"
        reports.append(image_report)
    return {
        "schema": "stpd/host-capacity-v1", "read_only": True,
        "status": "attention" if any(item["status"] == "attention" for item in reports)
        else "unknown" if any(item["status"] != "ok" for item in reports) else "ok",
        "same_filesystem": shared, "filesystems": reports,
        "additional_bytes": additional_bytes, "additional_inodes": additional_inodes,
        "automatic_cleanup": False, "work_reservation": "not_performed",
    }
