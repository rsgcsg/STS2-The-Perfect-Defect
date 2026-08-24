"""Exact identity checks for the versioned Connector consumer SDK."""

from __future__ import annotations

from pathlib import Path

from ..package_identity import (
    PackageIdentityError,
    file_sha256,
    validate_installed_package,
)
from .s1 import LiveS1Error


def validate_connector_sdk(sdk_root: Path, expected_raw: object) -> dict[str, str]:
    """Fail closed unless the installed SDK matches the pinned package identity."""
    entrypoint = sdk_root / "dist" / "index.js"
    try:
        identity = validate_installed_package(
            sdk_root,
            expected_raw,
            required_paths=("dist/index.js",),
        )
    except PackageIdentityError as error:
        raise LiveS1Error(f"Connector SDK {error}") from error
    return {
        **identity,
        "entrypoint": str(entrypoint.resolve()),
        "entrypoint_sha256": file_sha256(entrypoint),
    }
