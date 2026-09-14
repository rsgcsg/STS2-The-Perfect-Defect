"""Install only the reviewed optional Platform Runtime release, without lifecycle scripts."""

from __future__ import annotations

import hashlib
import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from ..canonical import canonical_json
from ..json_boundary import BoundaryError, digest
from ..package_identity import (
    PackageIdentityError,
    directory_sha256,
    file_sha256,
    validate_installed_package,
)

RUNTIME_PACKAGE = "@rsgcsg/sts2-policy-runtime"
CONNECTOR_PACKAGE = "@rsgcsg/sts2-connector-client"
ARCHIVE_LIMIT = 32 * 1024 * 1024
RELEASE_PREFIX = "https://github.com/rsgcsg/STS2-AI-PLATFORM/releases/download/"


class ReleaseRedirect(HTTPRedirectHandler):
    """GitHub release assets redirect to GitHub-owned storage; never send credentials."""

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        parsed = urlsplit(newurl)
        if (
            parsed.scheme != "https"
            or parsed.hostname
            not in {
                "github.com",
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            }
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
        ):
            raise BoundaryError("local_model", "untrusted_runtime_release_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_runtime_install(
    node_modules: Path, pin: dict[str, Any], connector_pin: dict[str, Any]
) -> dict[str, str]:
    package = node_modules / RUNTIME_PACKAGE
    connector = node_modules / CONNECTOR_PACKAGE
    if any(
        path.is_symlink() or not path.resolve().is_relative_to(node_modules.resolve())
        for path in (package, connector)
    ):
        raise PackageIdentityError("sibling Platform packages are unsupported")
    observed = validate_installed_package(
        package, pin, required_paths=("dist/cli.js", "bin/policy-runtime.mjs")
    )
    validate_installed_package(connector, connector_pin, required_paths=("package.json",))
    dependencies = pin.get("dependency_content_sha256")
    if not isinstance(dependencies, dict) or set(dependencies) != {"zod"}:
        raise PackageIdentityError("Runtime dependency closure pin is absent")
    zod = node_modules / "zod"
    if zod.is_symlink() or directory_sha256(zod) != dependencies["zod"]:
        raise PackageIdentityError("Runtime dependency content differs from pin")
    checksum = hashlib.sha256()
    for path in sorted((package / "dist").glob("*.js")):
        checksum.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return {**observed, "code_sha256": checksum.hexdigest()}


def install_runtime(
    directory: Path,
    pin: dict[str, Any],
    connector_pin: dict[str, Any],
    *,
    archive: Path | None = None,
) -> dict[str, Any]:
    """A local archive is an explicit CLI-only input, still bound to the release hash."""
    from .developer_server import instance_lock

    with instance_lock(directory / "runtime-install.lock"):
        try:
            return _install_runtime(directory, pin, connector_pin, archive=archive)
        except PackageIdentityError:
            raise BoundaryError(
                "local_model", "pinned_runtime_install_verification_failed"
            ) from None


def _install_runtime(
    directory: Path,
    pin: dict[str, Any],
    connector_pin: dict[str, Any],
    *,
    archive: Path | None,
) -> dict[str, Any]:
    expected = digest(pin.get("release_asset_sha256"), "local_model.runtime_archive")
    if pin.get("package") != RUNTIME_PACKAGE or not shutil.which("npm"):
        raise BoundaryError("local_model", "pinned_runtime_or_npm_missing")
    # Never replace the package beneath a runtime, including a previous workbench's process.
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 15527))
        except OSError:
            raise BoundaryError("local_model", "stop_runtime_before_install") from None
    directory.mkdir(parents=True, exist_ok=True)
    stage = directory / (".runtime-install-" + uuid4().hex)
    target = directory / "runtime"
    backup = directory / (".runtime-backup-" + uuid4().hex)
    installed = False
    try:
        stage.mkdir(mode=0o700)
        payload = stage / "runtime.tgz"
        if archive is not None:
            if (
                archive.is_symlink()
                or not archive.is_file()
                or archive.stat().st_size > ARCHIVE_LIMIT
            ):
                raise BoundaryError("local_model", "runtime_archive_missing_or_unsafe")
            shutil.copyfile(archive, payload)
        else:
            url = pin.get("release_url")
            if not isinstance(url, str) or not url.startswith(RELEASE_PREFIX):
                raise BoundaryError("local_model", "runtime_release_url_not_pinned")
            request = Request(url, headers={"Accept": "application/octet-stream"})
            size = 0
            try:
                with (
                    build_opener(ProxyHandler({}), ReleaseRedirect()).open(
                        request, timeout=30
                    ) as response,
                    payload.open("xb") as handle,
                ):
                    while block := response.read(1024 * 1024):
                        size += len(block)
                        if size > ARCHIVE_LIMIT:
                            raise BoundaryError("local_model", "runtime_archive_too_large")
                        handle.write(block)
            except OSError:
                raise BoundaryError("local_model", "pinned_runtime_release_unavailable") from None
        if file_sha256(payload) != expected:
            raise BoundaryError("local_model", "runtime_archive_checksum_mismatch")
        # The verified package carries an npm shrinkwrap with exact Connector and zod integrity.
        # npm gets a fixed argument vector and no user/global npm credentials or install scripts.
        (stage / "package.json").write_text(
            canonical_json(
                {
                    "name": "stpd-private-runtime",
                    "version": "0.0.0",
                    "private": True,
                    "dependencies": {RUNTIME_PACKAGE: "file:runtime.tgz"},
                }
            ),
            encoding="utf-8",
        )
        (stage / "user.npmrc").touch(mode=0o600)
        (stage / "global.npmrc").touch(mode=0o600)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "SYSTEMROOT", "SystemRoot", "TMPDIR", "TEMP", "TMP"}
        }
        environment.update(
            {
                "NPM_CONFIG_USERCONFIG": str(stage / "user.npmrc"),
                "NPM_CONFIG_GLOBALCONFIG": str(stage / "global.npmrc"),
                "NPM_CONFIG_CACHE": str(directory / "npm-cache"),
            }
        )
        with (stage / "install.log").open("wb") as log:
            result = subprocess.run(
                ["npm", "install", "--ignore-scripts", "--omit=dev", "--no-audit", "--no-fund"],
                cwd=stage,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=300,
                check=False,
            )
        if result.returncode != 0:
            raise BoundaryError("local_model", "pinned_runtime_npm_install_failed")
        observed = validate_runtime_install(stage / "node_modules", pin, connector_pin)
        if target.is_symlink():
            raise BoundaryError("local_model", "runtime_install_path_unsafe")
        if target.exists():
            target.rename(backup)
        try:
            stage.rename(target)
        except OSError:
            if backup.exists():
                backup.rename(target)
            raise
        installed = True
        return {
            "schema": "stpd/local-models-v1",
            "status": "runtime_installed",
            "runtime_package": observed,
            "loaded": False,
            "activated": False,
        }
    finally:
        if stage.is_dir():
            shutil.rmtree(stage)
        if installed and backup.is_dir():
            shutil.rmtree(backup)
