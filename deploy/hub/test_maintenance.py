"""Portable maintenance failure/age/identity checks; no Docker, credentials or cloud."""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import maintenance
from test_support import PosixPermissionFixture

IMAGE = "registry.example/stpd@sha256:" + "c" * 64
RECEIPT = "d" * 64


class MaintenanceTests(PosixPermissionFixture):
    def config(self, root: Path) -> tuple[Path, Path, Path]:
        root.chmod(0o700)
        config, secrets = root / "deployment.env", root / "backup.env"
        config.write_text(f"STPD_WORKER_IMAGE={IMAGE}\nSTPD_HUB_STATE_DIR={root}\n")
        secrets.write_text("AWS_ACCESS_KEY_ID=private-test-key\n"
                           "AWS_SECRET_ACCESS_KEY=private-test-secret-$()\n"
                           "STPD_S3_ENDPOINT=https://store.example\nSTPD_BACKUP_BUCKET=backup\n")
        config.chmod(0o600)
        secrets.chmod(0o600)
        return config, secrets, root / "status.json"

    def test_success_preserves_exact_receipt_and_never_expands_secret_into_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config, secrets, status = self.config(Path(directory))
            output = json.dumps({"schema": "stpd/hub-backup-command-v1",
                                 "backup_receipt": RECEIPT, "off_host_readback": "PASS",
                                 "restore_mode": "paused"})
            child = subprocess.CompletedProcess([], 0, output, "private-sdk-diagnostics")
            with patch.object(maintenance.subprocess, "run", return_value=child) as run:
                result = maintenance.run_backup(config, secrets, status)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--env-file") + 1], str(secrets))
            self.assertNotIn("private-test", " ".join(command))
            self.assertNotIn("--privileged", command)
            self.assertIn("--discard-local-after-verified", command)
            self.assertEqual(result["worker_image"], IMAGE)
            self.assertEqual(result["last_backup_receipt"], RECEIPT)
            self.assertEqual(maintenance.health(result)["backup_health"], "PASS")
            self.assertEqual(json.loads(status.read_bytes()), result)
            self.assertEqual(status.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("private-sdk", status.read_text())

    def test_failure_keeps_last_good_recovery_point_and_reports_no_sdk_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config, secrets, status = self.config(Path(directory))
            previous = {"schema": maintenance.SCHEMA, "last_status": "success",
                        "last_success_at": datetime.now(UTC).isoformat(),
                        "last_backup_receipt": RECEIPT, "worker_image": IMAGE}
            maintenance.write_status(status, previous)
            child = subprocess.CompletedProcess([], 2, "private-response", "private-sdk-error")
            with patch.object(maintenance.subprocess, "run", return_value=child):
                result = maintenance.run_backup(config, secrets, status)
            self.assertEqual(result["last_status"], "failed")
            self.assertEqual(result["last_backup_receipt"], RECEIPT)
            self.assertEqual(result["last_success_at"], previous["last_success_at"])
            self.assertEqual(maintenance.health(result)["backup_health"], "ATTENTION_REQUIRED")
            self.assertNotIn("private-", json.dumps(result))

    def test_timeout_stops_only_its_exact_named_container_and_does_not_claim_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config, secrets, status = self.config(Path(directory))
            with patch.object(maintenance.subprocess, "run", side_effect=[
                subprocess.TimeoutExpired("redacted", 900), subprocess.CompletedProcess([], 0),
            ]) as run:
                result = maintenance.run_backup(config, secrets, status)
            launch, stop = (call.args[0] for call in run.call_args_list)
            self.assertEqual(stop, ["docker", "stop", "--time", "30",
                                    launch[launch.index("--name") + 1]])
            self.assertEqual(result["last_error"], "backup_timeout_stopped")
            self.assertNotIn("last_success_at", result)

    def test_stale_missing_future_and_interrupted_attempts_cannot_be_green(self) -> None:
        now = datetime.now(UTC)
        for value in ({"schema": maintenance.SCHEMA},
                      {"last_status": "success", "last_success_at": "malformed"},
                      {"last_status": "running", "last_success_at": now.isoformat()},
                      {"last_status": "success", "last_success_at": (
                          now - timedelta(hours=27)).isoformat()},
                      {"last_status": "success", "last_success_at": (
                          now + timedelta(hours=1)).isoformat()}):
            self.assertEqual(maintenance.health(value, now=now)["backup_health"],
                             "ATTENTION_REQUIRED")

    def test_config_or_child_receipt_failure_is_persistent_without_losing_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config, secrets, status = self.config(Path(directory))
            config.write_text(config.read_text().replace(IMAGE, "registry.example/stpd:latest"))
            with patch.object(maintenance.subprocess, "run") as run:
                result = maintenance.run_backup(config, secrets, status)
            run.assert_not_called()
            self.assertEqual(result["last_error"], "immutable_backup_image_required")
            config.write_text(config.read_text().replace("registry.example/stpd:latest", IMAGE))
            for output in ("{}", "private-not-json", json.dumps({"backup_receipt": RECEIPT})):
                with patch.object(maintenance.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0, output, "")):
                    result = maintenance.run_backup(config, secrets, status)
                self.assertEqual(result["last_status"], "failed")
                self.assertNotIn("last_success_at", result)
