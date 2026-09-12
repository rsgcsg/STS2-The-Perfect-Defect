"""Private operational backup transport; never publishes research artifacts or restores live DBs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from preflight import IMAGE_PATTERN, PreflightError, check_backup

from stpd.storage.blobs import BlobStore
from stpd.storage.s3 import S3BlobStore, S3Config

CHUNK_BYTES = 4 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024


class BackupError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def current_database(path: Path, schema_version: int) -> None:
    """Inspect live WAL-aware version before invoking an owner that may migrate schemas."""
    if not path.is_file() or path.is_symlink():
        raise BackupError("existing_hub_database_required")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA user_version").fetchone() != (schema_version,):
            raise BackupError("backup_requires_current_schema_without_migration")


def checked_snapshot(path: Path, schema_version: int) -> None:
    check_backup(path)
    with closing(sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True,
    )) as db:
        if db.execute("PRAGMA user_version").fetchone() != (schema_version,):
            raise BackupError("backup_schema_incompatible_with_running_code")
    if not 0 < path.stat().st_size <= MAX_SNAPSHOT_BYTES:
        raise BackupError("backup_size_exceeds_bounded_transport")


def put_verified(store: BlobStore, key: str, data: bytes) -> None:
    store.put_if_absent(key, data)
    if store.get(key) != data:
        raise BackupError("backup_remote_readback_mismatch")


def upload_snapshot(
    store: BlobStore, snapshot: Path, producer: dict[str, str], image: str, schema_version: int,
) -> str:
    """Closed owning-API snapshot -> bounded immutable private blobs + commit manifest."""
    if re.fullmatch(IMAGE_PATTERN, image) is None:
        raise BackupError("exact_worker_image_required")
    checked_snapshot(snapshot, schema_version)
    chunks = []
    full_hash = hashlib.sha256()
    total = 0
    with snapshot.open("rb") as stream:
        while part := stream.read(CHUNK_BYTES):
            total += len(part)
            if total > MAX_SNAPSHOT_BYTES:
                raise BackupError("backup_size_exceeds_bounded_transport")
            full_hash.update(part)
            chunk_hash = digest(part)
            put_verified(store, f"chunks/{chunk_hash}", part)
            chunks.append({"sha256": chunk_hash, "size": len(part)})
    manifest = {
        "schema": "stpd/private-operations-backup-v1", "database_schema": schema_version,
        "producer": producer, "worker_image": image,
        "created_at": datetime.now(UTC).isoformat(), "restore_paused": True,
        "sha256": full_hash.hexdigest(), "size": total, "chunks": chunks,
    }
    encoded = canonical(manifest)
    receipt_id = digest(encoded)
    put_verified(store, f"receipts/{receipt_id}.json", encoded)
    return receipt_id


def load_manifest(store: BlobStore, receipt_id: str, schema_version: int) -> dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{64}", receipt_id) is None:
        raise BackupError("invalid_backup_receipt_id")
    encoded = store.get(f"receipts/{receipt_id}.json")
    if len(encoded) > MAX_MANIFEST_BYTES or digest(encoded) != receipt_id:
        raise BackupError("backup_manifest_digest_mismatch")
    value = json.loads(encoded)
    if not isinstance(value, dict) or canonical(value) != encoded or set(value) != {
        "schema", "database_schema", "producer", "worker_image", "created_at",
        "restore_paused", "sha256", "size", "chunks",
    }:
        raise BackupError("backup_manifest_shape_invalid")
    if (
        value["schema"] != "stpd/private-operations-backup-v1"
        or type(value["database_schema"]) is not int or value["database_schema"] != schema_version
        or value["restore_paused"] is not True
        or type(value["size"]) is not int or not 0 < value["size"] <= MAX_SNAPSHOT_BYTES
        or not isinstance(value["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
        or not isinstance(value["worker_image"], str)
        or re.fullmatch(IMAGE_PATTERN, value["worker_image"]) is None
    ):
        raise BackupError("backup_manifest_contract_invalid")
    from stpd.artifact_contracts import Producer

    Producer.decode(value["producer"])
    datetime.fromisoformat(value["created_at"])
    chunks = value["chunks"]
    if not isinstance(chunks, list) or not 1 <= len(chunks) <= MAX_SNAPSHOT_BYTES // CHUNK_BYTES:
        raise BackupError("backup_chunk_plan_invalid")
    total = 0
    for index, chunk in enumerate(chunks):
        if (
            not isinstance(chunk, dict) or set(chunk) != {"sha256", "size"}
            or not isinstance(chunk["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", chunk["sha256"]) is None
            or type(chunk["size"]) is not int or not 0 < chunk["size"] <= CHUNK_BYTES
            or (index < len(chunks) - 1 and chunk["size"] != CHUNK_BYTES)
        ):
            raise BackupError("backup_chunk_plan_invalid")
        total += chunk["size"]
    if total != value["size"]:
        raise BackupError("backup_chunk_plan_invalid")
    return value


def restore_check(
    store: BlobStore, receipt_id: str, destination: Path, schema_version: int,
) -> dict[str, Any]:
    """Retrieve into a new file only; validate before returning. Never replaces existing state."""
    manifest = load_manifest(store, receipt_id, schema_version)
    if destination.exists() or destination.is_symlink():
        raise BackupError("restore_destination_must_be_new")
    created = False
    try:
        with destination.open("xb") as stream:
            created = True
            destination.chmod(0o600)
            full_hash = hashlib.sha256()
            for chunk in manifest["chunks"]:
                part = store.get(f"chunks/{chunk['sha256']}")
                if len(part) != chunk["size"] or digest(part) != chunk["sha256"]:
                    raise BackupError("backup_chunk_digest_mismatch")
                stream.write(part)
                full_hash.update(part)
            stream.flush()
            os.fsync(stream.fileno())
        if full_hash.hexdigest() != manifest["sha256"]:
            raise BackupError("backup_snapshot_digest_mismatch")
        checked_snapshot(destination, schema_version)
        return manifest
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def configured_store() -> S3BlobStore:
    bucket = os.environ.get("STPD_BACKUP_BUCKET", "")
    endpoint = os.environ.get("STPD_S3_ENDPOINT", "")
    if (
        not bucket
        or bucket in {os.environ.get("STPD_S3_BUCKET"), os.environ.get("STPD_INGRESS_BUCKET")}
        or not endpoint.startswith("https://")
    ):
        raise BackupError("separate_private_backup_bucket_and_https_endpoint_required")
    if not os.environ.get("AWS_ACCESS_KEY_ID") or not os.environ.get("AWS_SECRET_ACCESS_KEY"):
        raise BackupError("scoped_operator_backup_credentials_required")
    return S3BlobStore(S3Config(
        bucket=bucket, endpoint=endpoint, prefix="private-operations-v1",
        region=os.environ.get("STPD_S3_REGION", "auto"),
    ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["backup", "restore-check"])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--state", type=Path, default=Path("/var/lib/stpd"))
    parser.add_argument("--receipt")
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args(argv)
    try:
        from stpd.hub.database import CURRENT_SCHEMA, Operations
        from stpd.workbench.control import source_identity

        producer = source_identity(args.root)
        store = configured_store()
        if args.command == "backup":
            database = args.state / "operations.sqlite"
            current_database(database, CURRENT_SCHEMA)
            snapshot = args.state / "backups" / f"operations-{uuid.uuid4().hex}.sqlite"
            Operations(database).backup(snapshot)
            receipt = upload_snapshot(
                store, snapshot, producer.to_dict(), os.environ.get("STPD_WORKER_IMAGE", ""),
                CURRENT_SCHEMA,
            )
            print(json.dumps({"schema": "stpd/hub-backup-command-v1", "backup_receipt": receipt,
                              "off_host_readback": "PASS", "restore_mode": "paused"}))
        else:
            if args.receipt is None or args.destination is None:
                raise BackupError("receipt_and_new_destination_required")
            manifest = restore_check(store, args.receipt, args.destination, CURRENT_SCHEMA)
            print(json.dumps({"schema": "stpd/hub-backup-command-v1",
                              "backup_receipt": args.receipt,
                              "restore_check": "PASS", "restore_mode": "paused",
                              "sha256": manifest["sha256"], "producer": manifest["producer"],
                              "worker_image": manifest["worker_image"]}))
        return 0
    except Exception as error:
        code = (str(error) if isinstance(error, (BackupError, PreflightError))
                else type(error).__name__)
        print(json.dumps({"schema": "stpd/hub-backup-command-v1", "error": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
