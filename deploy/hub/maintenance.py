"""Host-only scheduled backup and private freshness status. Never enables compute or restores."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from preflight import IMAGE_PATTERN, PUBLIC_KEYS, PreflightError, read_env

SCHEMA = "stpd/hub-backup-status-v1"
BACKUP_KEYS = {
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "STPD_S3_ENDPOINT",
    "STPD_S3_REGION", "STPD_BACKUP_BUCKET",
}
MAX_AGE_SECONDS = 26 * 3600


def read_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": SCHEMA}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
        raise PreflightError("backup_status_requires_bounded_regular_file")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise PreflightError("backup_status_schema_invalid")
    return value


def write_status(path: Path, value: dict[str, Any]) -> None:
    """One bounded atomic projection; immutable off-host receipts remain the backup authority."""
    import os

    if path.parent.is_symlink() or path.parent.stat().st_mode & 0o077:
        raise PreflightError("backup_status_directory_must_be_private")
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
        "docker", "run", "--rm", "--pull", "never", "--name", container,
        "--platform", "linux/amd64",
        "--user", "10001:10001", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--memory", "512m", "--memory-swap", "512m",
        "--cpus", "1", "--pids-limit", "64", "--stop-timeout", "30",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m,mode=1777",
        "--env-file", str(backup_env), "--env", f"STPD_WORKER_IMAGE={image}",
        "--env", "GIT_CONFIG_COUNT=1", "--env", "GIT_CONFIG_KEY_0=safe.directory",
        "--env", "GIT_CONFIG_VALUE_0=/opt/stpd", "--env", "GIT_OPTIONAL_LOCKS=0",
        "--mount", f"type=bind,src={state},dst=/var/lib/stpd", image,
        "/opt/stpd/.venv/bin/python", "/opt/stpd/deploy/hub/backup.py", "backup",
        "--discard-local-after-verified",
    ], image


def run_backup(config: Path, backup_env: Path, status_file: Path) -> dict[str, Any]:
    previous = read_status(status_file)
    status = {"schema": SCHEMA, "last_attempt_at": datetime.now(UTC).isoformat(),
              "last_status": "running"}
    for field in ("last_success_at", "last_backup_receipt", "worker_image"):
        if field in previous:
            status[field] = previous[field]
    write_status(status_file, status)
    container = "stpd-backup-" + uuid.uuid4().hex
    try:
        command, image = backup_command(config, backup_env, container)
        result = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
        if result.returncode:
            raise PreflightError("backup_container_failed_inspect_protected_state")
        reply = json.loads(result.stdout)
        receipt = reply.get("backup_receipt") if isinstance(reply, dict) else None
        if (
            not isinstance(reply, dict) or reply.get("schema") != "stpd/hub-backup-command-v1"
            or reply.get("off_host_readback") != "PASS" or reply.get("restore_mode") != "paused"
            or not isinstance(receipt, str) or re.fullmatch(r"[0-9a-f]{64}", receipt) is None
        ):
            raise PreflightError("backup_container_receipt_invalid")
        status.update(last_status="success", last_success_at=datetime.now(UTC).isoformat(),
                      last_backup_receipt=receipt, worker_image=image)
    except subprocess.TimeoutExpired:
        # Docker CLI termination alone does not stop its container. Stop only this run's name.
        try:
            stopped = subprocess.run(["docker", "stop", "--time", "30", container],
                                     capture_output=True, timeout=45, check=False)
            stop_status = "stopped" if stopped.returncode == 0 else "stop_unconfirmed"
        except (OSError, subprocess.TimeoutExpired):
            stop_status = "stop_unconfirmed"
        status.update(last_status="failed", last_error=f"backup_timeout_{stop_status}")
    except Exception as error:
        # Child stdout/stderr, SDK messages, env values and command text are never published.
        code = str(error) if isinstance(error, PreflightError) else type(error).__name__
        status.update(last_status="failed", last_error=code)
    write_status(status_file, status)
    return status


def health(value: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    try:
        elapsed = (now - datetime.fromisoformat(value["last_success_at"])).total_seconds()
        recent = 0 <= elapsed <= MAX_AGE_SECONDS
    except (KeyError, TypeError, ValueError):
        elapsed, recent = None, False
    healthy = recent and value.get("last_status") == "success"
    return {**value, "backup_health": "PASS" if healthy else "ATTENTION_REQUIRED",
            "age_seconds": elapsed, "maximum_age_seconds": MAX_AGE_SECONDS,
            "external_notification": "not_configured_by_this_tool"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["backup", "status"])
    parser.add_argument("--config", type=Path, default=Path("/etc/stpd/deployment.env"))
    parser.add_argument("--backup-env", type=Path, default=Path("/etc/stpd/hub-backup.env"))
    parser.add_argument("--status-file", type=Path,
                        default=Path("/var/lib/stpd-maintenance/backup-status.json"))
    args = parser.parse_args(argv)
    try:
        value = (run_backup(args.config, args.backup_env, args.status_file)
                 if args.command == "backup" else read_status(args.status_file))
        report = health(value)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["backup_health"] == "PASS" else 2
    except Exception as error:
        code = str(error) if isinstance(error, PreflightError) else type(error).__name__
        print(json.dumps({"schema": SCHEMA, "backup_health": "ATTENTION_REQUIRED", "error": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
