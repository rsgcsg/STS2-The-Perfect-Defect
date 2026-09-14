"""Host-only scheduled backup and private freshness status. Never enables compute or restores."""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from preflight import (
    IMAGE_PATTERN,
    PUBLIC_KEYS,
    PreflightError,
    check_capacity,
    operational_owner,
    owner_uid,
    read_env,
)

BACKUP_OWNER = operational_owner("backup_status")
SCHEMA = BACKUP_OWNER.SCHEMA
BACKUP_KEYS = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "STPD_S3_ENDPOINT",
    "STPD_S3_REGION",
    "STPD_BACKUP_BUCKET",
}
MAX_AGE_SECONDS = BACKUP_OWNER.MAX_AGE_SECONDS


def safe_status(value: dict[str, Any]) -> dict[str, Any]:
    return dict(BACKUP_OWNER.project(value))


def private_status_directory(directory: Path) -> None:
    if (
        directory.is_symlink()
        or not directory.is_dir()
        or directory.stat().st_mode & 0o777 != 0o700
        or (platform.system() == "Linux" and owner_uid(directory) != 0)
    ):
        raise PreflightError("backup_status_directory_requires_private_root_mode_0700")


def publish_safe_status(status_file: Path, value: dict[str, Any]) -> None:
    """A replace-visible directory projection; the private owner receipt stays authoritative."""
    import os

    parent = status_file.parent
    private_status_directory(parent)
    directory = parent / "safe-status"
    if directory.is_symlink():
        raise PreflightError("safe_status_directory_invalid")
    try:
        directory.mkdir(mode=0o755)
        directory.chmod(0o755)  # The backup unit intentionally runs with UMask=0077.
    except FileExistsError:
        pass
    if (
        not directory.is_dir()
        or directory.stat().st_mode & 0o777 != 0o755
        or owner_uid(directory) != owner_uid(parent)
    ):
        raise PreflightError("safe_status_directory_requires_mode_0755")
    safe = safe_status(value)
    temporary = directory / (".backup-" + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            temporary.chmod(0o644)
            json.dump(safe, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(directory / "backup-status.json")
        if os.name != "nt":
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def read_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": SCHEMA}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
        raise PreflightError("backup_status_requires_bounded_regular_file")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise PreflightError("backup_status_schema_invalid")
    return value


def write_status(path: Path, value: dict[str, Any]) -> bool:
    """One bounded atomic projection; immutable off-host receipts remain the backup authority."""
    import os

    private_status_directory(path.parent)
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            temporary.chmod(0o600)
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    try:
        publish_safe_status(path, value)
        return True
    except (OSError, ValueError, TypeError):
        return False


def backup_command(config: Path, backup_env: Path, container: str) -> tuple[list[str], str]:
    values = read_env(config, PUBLIC_KEYS, private=True)
    image = values.get("STPD_WORKER_IMAGE", "")
    if re.fullmatch(IMAGE_PATTERN, image) is None:
        raise PreflightError("immutable_backup_image_required")
    state = Path(values.get("STPD_HUB_STATE_DIR", ""))
    if not state.is_absolute() or not state.is_dir() or state.is_symlink() or "," in str(state):
        raise PreflightError("backup_state_requires_absolute_directory")
    secrets = read_env(backup_env, BACKUP_KEYS, private=True)
    required = BACKUP_KEYS - {"AWS_SESSION_TOKEN", "STPD_S3_REGION"}
    if any(not secrets.get(key) for key in required):
        raise PreflightError("backup_environment_incomplete")
    return [
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--name",
        container,
        "--platform",
        "linux/amd64",
        "--user",
        "10001:10001",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "512m",
        "--memory-swap",
        "512m",
        "--cpus",
        "1",
        "--pids-limit",
        "64",
        "--stop-timeout",
        "30",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=32m,mode=1777",
        "--env-file",
        str(backup_env),
        "--env",
        f"STPD_WORKER_IMAGE={image}",
        "--env",
        "GIT_CONFIG_COUNT=1",
        "--env",
        "GIT_CONFIG_KEY_0=safe.directory",
        "--env",
        "GIT_CONFIG_VALUE_0=/opt/stpd",
        "--env",
        "GIT_OPTIONAL_LOCKS=0",
        "--mount",
        f"type=bind,src={state},dst=/var/lib/stpd",
        image,
        "/opt/stpd/.venv/bin/python",
        "/opt/stpd/deploy/hub/backup.py",
        "backup",
        "--discard-local-after-verified",
    ], image


def run_backup(config: Path, backup_env: Path, status_file: Path) -> dict[str, Any]:
    previous = read_status(status_file)
    status = {
        "schema": SCHEMA,
        "last_attempt_at": datetime.now(UTC).isoformat(),
        "last_status": "running",
    }
    for field in ("last_success_at", "last_backup_receipt", "worker_image"):
        if field in previous:
            status[field] = previous[field]
    if not write_status(status_file, status):
        print(
            json.dumps(
                {
                    "stage": "backup_status_projection",
                    "phase": "running",
                    "status_projection": "unavailable",
                }
            ),
            file=sys.stderr,
            flush=True,
        )
    container = "stpd-backup-" + uuid.uuid4().hex
    try:
        command, image = backup_command(config, backup_env, container)
        result = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
        if result.returncode:
            raise PreflightError("backup_container_failed_inspect_protected_state")
        reply = json.loads(result.stdout)
        receipt = reply.get("backup_receipt") if isinstance(reply, dict) else None
        if (
            not isinstance(reply, dict)
            or reply.get("schema") != "stpd/hub-backup-command-v1"
            or reply.get("off_host_readback") != "PASS"
            or reply.get("restore_mode") != "paused"
            or not isinstance(receipt, str)
            or re.fullmatch(r"[0-9a-f]{64}", receipt) is None
        ):
            raise PreflightError("backup_container_receipt_invalid")
        status.update(
            last_status="success",
            last_success_at=datetime.now(UTC).isoformat(),
            last_backup_receipt=receipt,
            worker_image=image,
        )
    except subprocess.TimeoutExpired:
        # Docker CLI termination alone does not stop its container. Stop only this run's name.
        try:
            stopped = subprocess.run(
                ["docker", "stop", "--time", "30", container],
                capture_output=True,
                timeout=45,
                check=False,
            )
            stop_status = "stopped" if stopped.returncode == 0 else "stop_unconfirmed"
        except (OSError, subprocess.TimeoutExpired):
            stop_status = "stop_unconfirmed"
        status.update(last_status="failed", last_error=f"backup_timeout_{stop_status}")
    except Exception as error:
        # Child stdout/stderr, SDK messages, env values and command text are never published.
        code = str(error) if isinstance(error, PreflightError) else type(error).__name__
        status.update(last_status="failed", last_error=code)
    published = write_status(status_file, status)
    status["status_projection"] = "published" if published else "unavailable"
    return status


def health(value: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    return {
        **value,
        **BACKUP_OWNER.freshness(value, now=now),
        "external_notification": "not_configured_by_this_tool",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["backup", "status"])
    parser.add_argument("--config", type=Path, default=Path("/etc/stpd/deployment.env"))
    parser.add_argument("--backup-env", type=Path, default=Path("/etc/stpd/hub-backup.env"))
    parser.add_argument(
        "--status-file", type=Path, default=Path("/var/lib/stpd-maintenance/backup-status.json")
    )
    parser.add_argument(
        "--image-store",
        type=Path,
        default=Path("/var/lib/containerd"),
        help="actual Docker/containerd image directory; missing stays unknown",
    )
    args = parser.parse_args(argv)
    try:
        value = (
            run_backup(args.config, args.backup_env, args.status_file)
            if args.command == "backup"
            else read_status(args.status_file)
        )
        report = health(value)
        if args.command == "status":
            try:
                report["capacity"] = check_capacity(
                    args.config,
                    args.image_store,
                    additional_bytes=0,
                    additional_inodes=0,
                )
            except (OSError, ValueError, TypeError):
                report["capacity"] = {
                    "status": "unknown",
                    "error": "capacity_observation_unavailable",
                }
        print(json.dumps(report, sort_keys=True))
        if report["backup_health"] != "PASS":
            return 2
        if args.command == "status" and report["capacity"]["status"] != "ok":
            return 2
        return 2 if report.get("status_projection") == "unavailable" else 0
    except Exception as error:
        code = str(error) if isinstance(error, PreflightError) else type(error).__name__
        print(json.dumps({"schema": SCHEMA, "backup_health": "ATTENTION_REQUIRED", "error": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
