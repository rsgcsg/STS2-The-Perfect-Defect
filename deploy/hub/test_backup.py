"""Offline private backup transport failure conformance, with real SQLite bytes."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import backup
from test_support import PosixPermissionFixture

from stpd.storage.local import LocalBlobStore

PRODUCER = {"repository": "rsgcsg/STS2-The-Perfect-Defect", "source_revision": "a" * 40,
            "uv_lock_sha256": "b" * 64}
IMAGE = "registry.example/stpd@sha256:" + "c" * 64


def snapshot(path: Path, *, paused: str = "1", version: int = 2) -> None:
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO settings VALUES('paused',?)", (paused,))
        db.execute(f"PRAGMA user_version={version}")


class BackupTests(PosixPermissionFixture):
    def test_private_chunked_round_trip_keeps_exact_bytes_and_new_file_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.sqlite"
            snapshot(source)
            before = source.read_bytes()
            store = LocalBlobStore(root / "remote")
            with patch.object(backup, "CHUNK_BYTES", 4096):
                receipt = backup.upload_snapshot(store, source, PRODUCER, IMAGE, 2)
                target = root / "retrieved.sqlite"
                manifest = backup.restore_check(store, receipt, target, 2)
                self.assertGreater(len(manifest["chunks"]), 1)
                self.assertEqual(target.read_bytes(), before)
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
                with self.assertRaisesRegex(backup.BackupError, "must_be_new"):
                    backup.restore_check(store, receipt, target, 2)
                self.assertEqual(target.read_bytes(), before)
            keys = store.keys("receipts/") + store.keys("chunks/")
            self.assertTrue(all(key.startswith(("chunks/", "receipts/")) for key in keys))
            self.assertFalse(any("manifests/" in key or "run-completions/" in key for key in keys))

    def test_corrupt_chunk_and_manifest_reject_without_leftover_or_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.sqlite"
            snapshot(source)
            store = LocalBlobStore(root / "remote")
            receipt = backup.upload_snapshot(store, source, PRODUCER, IMAGE, 2)
            original_get = store.get

            def broken_chunk(key: str) -> bytes:
                value = original_get(key)
                return b"x" + value[1:] if key.startswith("chunks/") else value

            with patch.object(store, "get", side_effect=broken_chunk):
                target = root / "retrieved.sqlite"
                with self.assertRaisesRegex(backup.BackupError, "chunk_digest_mismatch"):
                    backup.restore_check(store, receipt, target, 2)
                self.assertFalse(target.exists())
            with (patch.object(store, "get", return_value=b"{}"),
                  self.assertRaisesRegex(backup.BackupError, "manifest_digest_mismatch")):
                    backup.restore_check(store, receipt, root / "unused", 2)
            self.assertFalse((root / "unused").exists())

    def test_live_schema_never_migrates_and_snapshot_requires_no_wal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "old.sqlite"
            snapshot(old, version=1)
            before = old.read_bytes()
            with self.assertRaisesRegex(backup.BackupError, "without_migration"):
                backup.current_database(old, 2)
            self.assertEqual(old.read_bytes(), before)
            current = root / "current.sqlite"
            snapshot(current, version=2)
            with closing(sqlite3.connect(current)) as db, db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("UPDATE settings SET value='1'")
                db.commit()
                backup.current_database(current, 2)
                with self.assertRaisesRegex(backup.PreflightError, "closed_without_wal"):
                    backup.checked_snapshot(current, 2)

    def test_future_schema_and_unpaused_cannot_be_uploaded_or_restored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = LocalBlobStore(root / "remote")
            future = root / "future.sqlite"
            snapshot(future, version=3)
            with self.assertRaisesRegex(backup.BackupError, "schema_incompatible"):
                backup.upload_snapshot(store, future, PRODUCER, IMAGE, 2)
            active = root / "active.sqlite"
            snapshot(active, paused="0")
            with self.assertRaisesRegex(backup.PreflightError, "restore_paused"):
                backup.upload_snapshot(store, active, PRODUCER, IMAGE, 2)
            good = root / "good.sqlite"
            snapshot(good)
            receipt = backup.upload_snapshot(store, good, PRODUCER, IMAGE, 2)
            with self.assertRaisesRegex(backup.BackupError, "contract_invalid"):
                backup.restore_check(store, receipt, root / "unused", 3)
            self.assertFalse((root / "unused").exists())

    def test_failed_remote_readback_does_not_publish_commit_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.sqlite"
            snapshot(source)
            store = LocalBlobStore(root / "remote")
            with (patch.object(store, "get", return_value=b"wrong"),
                  self.assertRaisesRegex(backup.BackupError, "remote_readback_mismatch")):
                    backup.upload_snapshot(store, source, PRODUCER, IMAGE, 2)
            self.assertEqual(store.keys("receipts/"), ())
            self.assertTrue(source.exists())

    def test_self_consistent_wrong_chunk_plan_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.sqlite"
            snapshot(source)
            store = LocalBlobStore(root / "remote")
            receipt = backup.upload_snapshot(store, source, PRODUCER, IMAGE, 2)
            manifest = json.loads(store.get(f"receipts/{receipt}.json"))
            manifest["size"] += 1
            encoded = backup.canonical(manifest)
            fake = backup.digest(encoded)
            store.put_if_absent(f"receipts/{fake}.json", encoded)
            with self.assertRaisesRegex(backup.BackupError, "chunk_plan_invalid"):
                backup.restore_check(store, fake, root / "unused", 2)
            self.assertFalse((root / "unused").exists())


if __name__ == "__main__":
    unittest.main()
