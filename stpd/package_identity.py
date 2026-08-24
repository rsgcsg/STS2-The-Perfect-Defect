"""Exact, filesystem-independent identity checks for public Platform packages."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path


class PackageIdentityError(RuntimeError):
    """An installed package does not match its immutable experiment pin."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def directory_sha256(directory: Path) -> str:
    """Hash package paths and bytes without depending on filesystem metadata."""
    digest = hashlib.sha256()
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(directory).as_posix().encode()
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def validate_installed_package(
    package_root: Path,
    expected_raw: object,
    *,
    required_paths: Sequence[str],
) -> dict[str, str]:
    """Fail closed unless one installed package matches its complete public pin."""
    if not isinstance(expected_raw, Mapping):
        raise PackageIdentityError("package identity pin is absent")
    required_identity = (
        "package",
        "version",
        "source_revision",
        "component_tree_revision",
        "release_asset_sha256",
        "package_content_sha256",
    )
    expected: dict[str, str] = {}
    for key in required_identity:
        value = expected_raw.get(key)
        if not isinstance(value, str) or not value:
            raise PackageIdentityError("package identity pin is incomplete")
        expected[key] = value

    package_json = package_root / "package.json"
    missing = [relative for relative in required_paths if not (package_root / relative).is_file()]
    if not package_json.is_file() or missing:
        raise PackageIdentityError("run npm ci to install the pinned Platform packages")
    package = json.loads(package_json.read_text(encoding="utf-8"))
    if package.get("name") != expected["package"]:
        raise PackageIdentityError("installed package name differs from pin")
    if package.get("version") != expected["version"]:
        raise PackageIdentityError("installed package version differs from pin")
    content_sha256 = directory_sha256(package_root)
    if content_sha256 != expected["package_content_sha256"]:
        raise PackageIdentityError("installed package content differs from pin")
    return {**expected, "package_content_sha256": content_sha256}
