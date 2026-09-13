"""Portable source checks only; Docker/TLS/storage runtime qualification is separate."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import preflight
from test_support import PosixPermissionFixture


class PreflightTests(PosixPermissionFixture):
    def test_browser_allowlist_is_optional_private_and_mounted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.assertEqual(preflight.check_console({}, root), {"browser_console": "disabled"})
            fields = {"STPD_ACCESS_ISSUER": "https://team.cloudflareaccess.com"}
            with self.assertRaisesRegex(preflight.PreflightError, "incomplete"):
                preflight.check_console(fields, root)
            fields.update(STPD_ACCESS_AUDIENCE="a" * 64,
                          STPD_ACCESS_ALLOWLIST="/var/lib/stpd/access.json")
            target = root / "access.json"
            target.write_text(json.dumps({"schema": "stpd/console-access-v1", "principals": [
                {"email": "test@example.org", "role": "collector", "devices": ["one"]}]}))
            target.chmod(0o600)
            with patch.object(preflight, "owner_uid", return_value=10001):
                self.assertEqual(preflight.check_console(fields, root),
                                 {"browser_console": "configured_not_live_qualified"})
                target.chmod(0o644)
                with self.assertRaisesRegex(preflight.PreflightError, "private_uid"):
                    preflight.check_console(fields, root)
                target.chmod(0o600)
                fields["STPD_ACCESS_ALLOWLIST"] = "/etc/private.json"
                with self.assertRaisesRegex(preflight.PreflightError, "mounted_state"):
                    preflight.check_console(fields, root)

    def test_named_modal_environment_is_accepted_without_enabling_compute(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env_file = root / "runtime.env"
            env_file.write_text("MODAL_ENVIRONMENT=spireagent-b\n")
            secrets = preflight.read_env(env_file, preflight.SECRET_KEYS)
            values = {"STPD_HUB_BUDGET_UNITS": "0"}
            self.assertEqual(preflight.check_compute(
                values, secrets, root, allow_compute=False,
            ), {"compute_budget": 0, "compute": "disabled"})
            for invalid in ("", "wrong/environment", "environment with spaces"):
                with self.assertRaisesRegex(preflight.PreflightError, "invalid_modal_environment"):
                    preflight.check_compute(
                        values, {"MODAL_ENVIRONMENT": invalid}, root, allow_compute=False,
                    )

    def test_configuration_is_read_only_and_never_reports_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("state/work", "state/backups", "tls/data", "tls/config"):
                (root / name).mkdir(parents=True, exist_ok=True)
            for path in root.rglob("*"):
                if path.is_dir():
                    path.chmod(0o700)
            secrets = root / "runtime.env"
            secrets.write_text(
                "STPD_HUB_ADMIN_TOKEN=" + "private-not-output-" * 3 + "\n"
                "AWS_ACCESS_KEY_ID=private-key\nAWS_SECRET_ACCESS_KEY=private-secret\n"
                "STPD_S3_ENDPOINT=https://account.r2.cloudflarestorage.com\n"
                "STPD_S3_BUCKET=artifacts\nSTPD_INGRESS_BUCKET=ingress\n"
            )
            secrets.chmod(0o600)
            fields = {
                "STPD_WORKER_IMAGE": "registry.example/stpd@sha256:" + "a" * 64,
                "STPD_CADDY_IMAGE": "docker.io/library/caddy@sha256:" + "b" * 64,
                "STPD_HUB_DOMAIN": "hub.example.org", "STPD_ACME_EMAIL": "ops@example.org",
                "STPD_HUB_STATE_DIR": str(root / "state"),
                "STPD_HUB_CADDY_DIR": str(root / "tls"),
                "STPD_HUB_SECRET_FILE": str(secrets), "STPD_HUB_BUDGET_UNITS": "0",
            }
            config = root / "deployment.env"
            config.write_text("".join(f"{key}={value}\n" for key, value in fields.items()))
            before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in (config, secrets)}
            with patch.object(preflight, "owner_uid", return_value=10001):
                report = preflight.check_configuration(config)
                self.assertEqual(report["configuration"], "PASS")
                self.assertNotIn("private-", json.dumps(report))
                (root / "state").chmod(0o755)
                with self.assertRaisesRegex(preflight.PreflightError, "must_be_private"):
                    preflight.check_configuration(config)
                (root / "state").chmod(0o700)
                secrets.chmod(0o644)
                with self.assertRaisesRegex(preflight.PreflightError, "mode_0600"):
                    preflight.check_configuration(config)
                secrets.chmod(0o600)
                config.write_text(config.read_text().replace("BUDGET_UNITS=0", "BUDGET_UNITS=1"))
                with self.assertRaisesRegex(preflight.PreflightError, "disable_compute_budget"):
                    preflight.check_configuration(config)
                config.write_text(config.read_text().replace("BUDGET_UNITS=1", "BUDGET_UNITS=0"))
            self.assertEqual(before, {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                      for path in (config, secrets)})

    def test_backup_reader_preserves_bytes_and_rejects_unpaused_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "operations.sqlite"
            with closing(sqlite3.connect(backup)) as db, db:
                db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
                db.execute("INSERT INTO settings VALUES('paused','1')")
            original = backup.read_bytes()
            self.assertEqual(preflight.check_backup(backup)["restore_mode"], "paused")
            self.assertEqual(backup.read_bytes(), original)
            with closing(sqlite3.connect(backup)) as db, db:
                db.execute("UPDATE settings SET value='0'")
            with self.assertRaisesRegex(preflight.PreflightError, "restore_paused"):
                preflight.check_backup(backup)

    def test_env_rejects_duplicates_and_shell_style_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "bad.env"
            for value in ("UNKNOWN=value", "export STPD_HUB_DOMAIN=x", "X=1\nX=2"):
                config.write_text(value)
                with self.assertRaises(preflight.PreflightError):
                    preflight.read_env(config, {"X"})

    def test_optional_compute_is_exact_mounted_and_explicitly_budgeted(self) -> None:
        producer = {"repository": "rsgcsg/STS2-The-Perfect-Defect", "source_revision": "a" * 40,
                    "uv_lock_sha256": "b" * 64}
        image = "registry.example/stpd@sha256:" + "c" * 64
        values = {"STPD_WORKER_IMAGE": image, "STPD_HUB_BUDGET_UNITS": "0"}
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory).resolve()
            target = state / "modal-target.json"
            target.write_text(json.dumps({"schema": "stpd/modal-target-v1", "producer": producer,
                                          "image": image, "gpu": "L4", "timeout_seconds": 300,
                                          "storage_secret_name": "storage",
                                          "qwen_volume_name": None}))
            target.chmod(0o600)
            secrets = {"STPD_MODAL_TARGET": "/var/lib/stpd/modal-target.json",
                       "MODAL_TOKEN_ID": "private-modal-id", "MODAL_TOKEN_SECRET": "private-secret"}
            original = target.read_bytes()
            with (patch.object(preflight, "owner_uid", return_value=10001),
                  patch.object(preflight, "checkout_identity", return_value=producer)):
                report = preflight.check_compute(values, secrets, state, allow_compute=False)
                self.assertEqual(report["compute"], "configured_budget_zero")
                self.assertNotIn("private-", json.dumps(report))
                self.assertEqual(target.read_bytes(), original)
                values["STPD_HUB_BUDGET_UNITS"] = "1"
                with self.assertRaisesRegex(preflight.PreflightError, "disable_compute_budget"):
                    preflight.check_compute(values, secrets, state, allow_compute=False)
                self.assertEqual(preflight.check_compute(
                    values, secrets, state, allow_compute=True,
                )["compute"], "explicitly_enabled")
                with self.assertRaisesRegex(preflight.PreflightError, "requires_exact_modal"):
                    preflight.check_compute(values, {}, state, allow_compute=True)
                values["STPD_HUB_BUDGET_UNITS"] = "0"
                incomplete = {"MODAL_TOKEN_ID": "private-modal-id"}
                with self.assertRaisesRegex(preflight.PreflightError, "environment_incomplete"):
                    preflight.check_compute(values, incomplete, state, allow_compute=False)
                for bad_path in ("/etc/target.json", "/var/lib/stpd/../target.json"):
                    secrets["STPD_MODAL_TARGET"] = bad_path
                    with self.assertRaisesRegex(preflight.PreflightError, "inside_mounted_state"):
                        preflight.check_compute(values, secrets, state, allow_compute=False)
                secrets["STPD_MODAL_TARGET"] = "/var/lib/stpd/modal-target.json"
                target.write_text(original.decode().replace("a" * 40, "d" * 40))
                with self.assertRaisesRegex(preflight.PreflightError, "source_lock_image_mismatch"):
                    preflight.check_compute(values, secrets, state, allow_compute=False)

    @unittest.skipIf(os.name == "nt", "Linux symlink guard requires POSIX fixture rights")
    def test_modal_target_symlinks_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory).resolve()
            target = state / "real.json"
            target.write_text("{}")
            (state / "linked.json").symlink_to(target)
            values = {"STPD_HUB_BUDGET_UNITS": "0"}
            secrets = {"STPD_MODAL_TARGET": "/var/lib/stpd/linked.json",
                       "MODAL_TOKEN_ID": "synthetic", "MODAL_TOKEN_SECRET": "synthetic"}
            with self.assertRaisesRegex(preflight.PreflightError, "symlinks_forbidden"):
                preflight.check_compute(values, secrets, state, allow_compute=False)

    def test_proxy_preserves_current_32_mib_upload_intent_contract(self) -> None:
        config = (Path(__file__).parent / "Caddyfile").read_text()
        self.assertIn("max_size 33554432", config)

    def test_ingress_does_not_expire_unverified_evidence(self) -> None:
        value = json.loads((Path(__file__).parent / "ingress-lifecycle.json").read_text())
        self.assertEqual(len(value["Rules"]), 1)
        rule = value["Rules"][0]
        self.assertEqual(rule["Filter"], {"Prefix": "incoming/"})
        self.assertEqual(rule["AbortIncompleteMultipartUpload"]["DaysAfterInitiation"], 1)
        self.assertNotIn("Expiration", rule)


if __name__ == "__main__":
    unittest.main()
