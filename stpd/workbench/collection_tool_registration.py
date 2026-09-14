"""Private registration of an operator-pinned public CollectionTool directory."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from sts2_platform_evidence.collection_tool import CollectionTool

from ..json_boundary import BoundaryError, decode_json, digest, object_fields
from .developer import ProjectConfig, atomic_json

SCHEMA = "stpd/collection-tool-registration-v1"
REGISTRATION_FILE = "collection-tool-registration.json"
REGISTRATION_LIMIT = 64 * 1024


def _tool(directory: Path, release_id: str) -> Path:
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise BoundaryError("collection_tool", "absolute_non_symlink_tool_directory_required")
    try:
        # The public owner validates the clean-source identity and complete byte inventory.
        CollectionTool(directory, release_id)
    except (OSError, ValueError, TypeError):
        raise BoundaryError(
            "collection_tool", "collection_tool_identity_verification_failed"
        ) from None
    return directory.resolve()


def _registration(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise BoundaryError(
            "collection_tool", "collection_tool_registration_missing_or_unsafe"
        ) from None
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_size > REGISTRATION_LIMIT
        or (os.name != "nt" and info.st_mode & 0o077)
    ):
        raise BoundaryError("collection_tool", "collection_tool_registration_missing_or_unsafe")
    value = object_fields(
        decode_json(path.read_bytes()),
        {"schema", "path", "release_id"},
        "collection_tool.registration",
    )
    if value["schema"] != SCHEMA or not isinstance(value["path"], str):
        raise BoundaryError("collection_tool", "collection_tool_registration_invalid")
    digest(value["release_id"], "collection_tool.release_id")
    return value


def register_collection_tool(
    config: ProjectConfig,
    directory: Path,
    release_id: str,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    """Register verified bytes without executing, packaging, binding or uploading anything."""
    from .developer_server import instance_lock

    identity = digest(release_id, "collection_tool.release_id")
    # The same OS-held lock as the workbench guarantees registration while it is stopped.
    with instance_lock(config.state_dir / "instance.lock"):
        tool = _tool(directory, identity)
        target = config.state_dir / REGISTRATION_FILE
        registration = {"schema": SCHEMA, "path": str(tool), "release_id": identity}
        if target.is_symlink():
            raise BoundaryError("collection_tool", "collection_tool_registration_missing_or_unsafe")
        if target.exists():
            try:
                previous = _registration(target)
            except (OSError, ValueError, BoundaryError):
                if not replace:
                    raise BoundaryError(
                        "collection_tool", "collection_tool_registration_invalid"
                    ) from None
                previous = None
            if previous == registration:
                return {
                    "schema": SCHEMA,
                    "status": "registered",
                    "release_id": identity,
                    "changed": False,
                }
            if not replace:
                raise BoundaryError(
                    "collection_tool", "collection_tool_registration_conflict_use_replace_tool"
                )
        atomic_json(target, registration)
        return {"schema": SCHEMA, "status": "registered", "release_id": identity, "changed": True}


def registered_collection_tool(config: ProjectConfig, expected_release_id: str) -> Path:
    """Resolve only the requested release after re-verifying its full current byte identity."""
    expected = digest(expected_release_id, "collection_tool.expected_release_id")
    registration = _registration(config.state_dir / REGISTRATION_FILE)
    if registration["release_id"] != expected:
        raise BoundaryError("collection_tool", "collection_tool_registered_release_mismatch")
    return _tool(Path(registration["path"]), expected)
