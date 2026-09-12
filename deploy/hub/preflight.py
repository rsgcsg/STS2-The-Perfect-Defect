"""Read-only Hub deployment checks. Never builds, starts, writes or prints credentials."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sqlite3
import stat
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

PUBLIC_KEYS = {
    "STPD_WORKER_IMAGE", "STPD_CADDY_IMAGE", "STPD_HUB_DOMAIN", "STPD_ACME_EMAIL",
    "STPD_HUB_STATE_DIR", "STPD_HUB_CADDY_DIR", "STPD_HUB_SECRET_FILE", "STPD_HUB_BUDGET_UNITS",
}
SECRET_KEYS = {
    "STPD_HUB_ADMIN_TOKEN", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "STPD_S3_ENDPOINT", "STPD_S3_REGION", "STPD_S3_BUCKET", "STPD_S3_PREFIX",
    "STPD_INGRESS_BUCKET",
}
REQUIRED_SECRET_KEYS = SECRET_KEYS - {"AWS_SESSION_TOKEN", "STPD_S3_REGION", "STPD_S3_PREFIX"}
IMAGE_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}"


class PreflightError(ValueError):
    pass


def read_env(path: Path, allowed: set[str], *, private: bool = False) -> dict[str, str]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024:
        raise PreflightError("env_requires_bounded_regular_file")
    if private and info.st_mode & 0o077:
        raise PreflightError("secret_file_requires_mode_0600")
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key not in allowed or key in result:
            raise PreflightError("env_unknown_or_duplicate_key")
        if value != value.strip() or any(ord(char) < 32 for char in value):
            raise PreflightError("env_invalid_raw_value")
        result[key] = value
    return result


def owner_uid(path: Path) -> int:
    return path.stat().st_uid


def check_configuration(config: Path) -> dict[str, Any]:
    values = read_env(config, PUBLIC_KEYS)
    if set(values) != PUBLIC_KEYS or any(not value for value in values.values()):
        raise PreflightError("deployment_fields_missing")
    for name in ("STPD_WORKER_IMAGE", "STPD_CADDY_IMAGE"):
        if re.fullmatch(IMAGE_PATTERN, values[name]) is None:
            raise PreflightError("immutable_image_digests_required")
    if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", values["STPD_HUB_DOMAIN"]) is None:
        raise PreflightError("public_dns_hostname_required")
    if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", values["STPD_ACME_EMAIL"]) is None:
        raise PreflightError("acme_contact_required")
    if values["STPD_HUB_BUDGET_UNITS"] != "0":
        raise PreflightError("initial_deployment_must_disable_compute_budget")
    paths = {}
    for name in ("STPD_HUB_STATE_DIR", "STPD_HUB_CADDY_DIR", "STPD_HUB_SECRET_FILE"):
        path = Path(values[name])
        if not path.is_absolute() or path.is_symlink():
            raise PreflightError("absolute_non_symlink_runtime_paths_required")
        if any((ancestor / ".git").exists() for ancestor in (path, *path.parents)):
            raise PreflightError("runtime_files_must_be_outside_git_checkout")
        paths[name] = path
    state, tls = paths["STPD_HUB_STATE_DIR"], paths["STPD_HUB_CADDY_DIR"]
    if state == tls or state in tls.parents or tls in state.parents:
        raise PreflightError("separate_application_and_tls_state_required")
    for path in (state, state / "work", state / "backups", tls, tls / "data", tls / "config"):
        if not path.is_dir() or path.is_symlink():
            raise PreflightError("persistent_directories_not_prepared")
        if path.stat().st_mode & 0o077:
            raise PreflightError("persistent_directories_must_be_private")
    if any(owner_uid(path) != 10001 for path in (state, state / "work", state / "backups")):
        raise PreflightError("application_state_owner_must_be_uid_10001")
    secrets = read_env(paths["STPD_HUB_SECRET_FILE"], SECRET_KEYS, private=True)
    if any(not secrets.get(name) for name in REQUIRED_SECRET_KEYS):
        raise PreflightError("runtime_environment_incomplete")
    if len(secrets["STPD_HUB_ADMIN_TOKEN"]) < 32:
        raise PreflightError("admin_credential_too_short")
    endpoint = urlsplit(secrets["STPD_S3_ENDPOINT"])
    if (
        endpoint.scheme != "https" or not endpoint.hostname
        or endpoint.username or endpoint.password
        or endpoint.query or endpoint.fragment
    ):
        raise PreflightError("private_store_https_endpoint_required")
    if secrets["STPD_S3_BUCKET"] == secrets["STPD_INGRESS_BUCKET"]:
        raise PreflightError("separate_ingress_and_artifact_buckets_required")
    return {
        "configuration": "PASS", "credential_values": "not_reported", "compute_budget": 0,
        "checks_not_performed": ["DNS ownership", "TLS issuance", "bucket privacy", "cloud IAM",
                                 "loaded OCI identity", "real upload", "real GPU"],
    }


def check_backup(path: Path) -> dict[str, str]:
    """Open an already produced consistent backup without touching its bytes."""
    if path.is_symlink() or not path.is_file():
        raise PreflightError("backup_regular_file_required")
    if Path(str(path) + "-wal").exists() or Path(str(path) + "-shm").exists():
        raise PreflightError("backup_must_be_closed_without_wal_or_shm")
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise PreflightError("backup_integrity_failure")
        row = db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
        if row != ("1",):
            raise PreflightError("backup_must_restore_paused")
    return {"backup_integrity": "PASS", "restore_mode": "paused"}


def host_checks() -> dict[str, Any]:
    if platform.system() != "Linux":
        raise PreflightError("deployment_requires_linux_host")
    if platform.machine() not in {"x86_64", "amd64"}:
        raise PreflightError("deployment_requires_qualified_amd64_image_host")
    if not shutil.which("docker"):
        raise PreflightError("docker_engine_and_compose_required")
    result = subprocess.run(
        ["docker", "compose", "version", "--short"], capture_output=True, text=True,
        check=False, timeout=10,
    )
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", result.stdout.strip())
    if result.returncode or match is None or tuple(map(int, match.groups())) < (2, 30, 0):
        raise PreflightError("compose_2_30_or_newer_required")
    memory = int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    return {
        "host": "PASS", "physical_memory_mib": memory // 1024**2,
        "capacity_note": "4_GiB_recommended_measure_before_raising_limits",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--host", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not (args.config or args.backup or args.host):
            raise PreflightError("select_config_backup_or_host_checks")
        report: dict[str, Any] = {"schema": "stpd/hub-preflight-v1", "read_only": True}
        if args.config:
            report.update(check_configuration(args.config))
        if args.backup:
            report.update(check_backup(args.backup))
        if args.host:
            report.update(host_checks())
        print(json.dumps(report))
        return 0
    except Exception as error:
        # Do not emit paths, SDK messages or any parsed configuration values.
        code = str(error) if isinstance(error, PreflightError) else type(error).__name__
        print(json.dumps({"schema": "stpd/hub-preflight-v1", "read_only": True, "error": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
