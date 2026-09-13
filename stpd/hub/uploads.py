"""Bounded untrusted ingress; exact Platform verification precedes trusted publication."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import tarfile
import tempfile
import time
import uuid
import zlib
from contextlib import suppress
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Protocol, cast

from sts2_platform_evidence import DirectoryTransferManifest, verify_human_session_bundle
from sts2_platform_evidence.human_session_bundle import VerifiedHumanSessionBundle

from ..artifact_contracts import Manifest, Producer
from ..json_boundary import BoundaryError, FrozenObject, digest, json_bytes, object_fields
from ..storage.store import ArtifactStore
from .database import Operations

MAX_ARCHIVE = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024
MAX_FILES = 50000


class Staging(Protocol):
    def authorize(self, upload_id: str, size: int) -> tuple[str, dict[str, str]]: ...
    def download(self, upload_id: str, target: BinaryIO, size: int) -> None: ...


class LocalStaging:
    """Explicit development transport. HTTP endpoint still requires its upload capability."""

    def __init__(self, root: Path, public_url: str) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.public_url = public_url.rstrip("/")

    def authorize(self, upload_id: str, size: int) -> tuple[str, dict[str, str]]:
        return f"{self.public_url}/v1/uploads/{upload_id}/body", {}

    def write(self, upload_id: str, body: BinaryIO, size: int) -> None:
        destination = self.root / upload_id
        temporary = self.root / (upload_id + "." + uuid.uuid4().hex + ".uploading")
        try:
            with temporary.open("xb") as handle:
                remaining = size
                while remaining:
                    chunk = body.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise BoundaryError("upload", "truncated_body")
                    handle.write(chunk)
                    remaining -= len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                with temporary.open("rb") as left, destination.open("rb") as right:
                    if (
                        hashlib.file_digest(left, "sha256").digest()
                        != hashlib.file_digest(right, "sha256").digest()
                    ):
                        raise BoundaryError("upload", "staging_collision") from None
        finally:
            temporary.unlink(missing_ok=True)

    def download(self, upload_id: str, target: BinaryIO, size: int) -> None:
        with (self.root / upload_id).open("rb") as source:
            _copy_exact(source, target, size)


class S3Staging:
    def __init__(self, client: Any, bucket: str, prefix: str = "incoming") -> None:
        from ..storage.blobs import safe_key

        self.client, self.bucket, self.prefix = client, bucket, safe_key(prefix)

    def authorize(self, upload_id: str, size: int) -> tuple[str, dict[str, str]]:
        url = self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": f"{self.prefix}/{upload_id}",
                "ContentLength": size,
                "ContentType": "application/gzip",
            },
            ExpiresIn=900,
        )
        return str(url), {"Content-Type": "application/gzip"}

    def download(self, upload_id: str, target: BinaryIO, size: int) -> None:
        response = self.client.get_object(Bucket=self.bucket, Key=f"{self.prefix}/{upload_id}")
        body = response["Body"]
        try:
            if response.get("ContentLength") != size:
                raise BoundaryError("upload", "archive_size_mismatch")
            _copy_exact(body, target, size)
        finally:
            body.close()


def _copy_exact(source: BinaryIO, target: BinaryIO, size: int) -> None:
    remaining = size
    while remaining:
        chunk = source.read(min(1024 * 1024, remaining))
        if not chunk:
            raise BoundaryError("upload", "truncated_archive")
        target.write(chunk)
        remaining -= len(chunk)
    if source.read(1):
        raise BoundaryError("upload", "archive_size_mismatch")


def transfer_from_json(value: object) -> DirectoryTransferManifest:
    # Use the public producer-owned codec, including its canonical manifest identity.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "transfer.json"
        path.write_bytes(json_bytes(value))
        result = DirectoryTransferManifest.read(path)
    if result.artifact_type != "human-session-bundle" or not 0 < len(result.files) <= MAX_FILES:
        raise BoundaryError("upload", "unsupported_inventory")
    if sum(file.bytes for file in result.files) > MAX_EXPANDED:
        raise BoundaryError("upload", "expanded_size_limit")
    return result


def unpack(archive: Path, directory: Path, transfer: DirectoryTransferManifest) -> None:
    # Bound the entire expanded stream before tarfile can allocate PAX/longname headers.
    with tempfile.TemporaryFile("w+b") as expanded:
        with gzip.open(archive, "rb") as source:
            total = 0
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_EXPANDED:
                    raise BoundaryError("upload", "expanded_stream_size_limit")
                expanded.write(chunk)
        expanded.seek(0)
        # Windows wraps TemporaryFile while retaining the binary file interface.
        _unpack_tar(cast(BinaryIO, expanded), directory, transfer)


def _unpack_tar(source_tar: BinaryIO, directory: Path, transfer: DirectoryTransferManifest) -> None:
    expected = {file.path: file for file in transfer.files}
    seen: set[str] = set()
    with tarfile.open(fileobj=source_tar, mode="r|") as stream:
        for entry in stream:
            name = entry.name
            path = PurePosixPath(name)
            if (
                not entry.isfile()
                or name not in expected
                or name in seen
                or path.is_absolute()
                or any(part in {"", ".", ".."} for part in path.parts)
                or "\\" in name
                or name != path.as_posix()
            ):
                raise BoundaryError("upload", "archive_inventory_mismatch")
            declared = expected[name]
            if entry.size != declared.bytes:
                raise BoundaryError("upload", "archive_entry_size_mismatch")
            destination = directory / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = stream.extractfile(entry)
            if source is None:
                raise BoundaryError("upload", "archive_member_missing")
            hasher = hashlib.sha256()
            with source, destination.open("xb") as target:
                while chunk := source.read(1024 * 1024):
                    hasher.update(chunk)
                    target.write(chunk)
            if hasher.hexdigest() != declared.sha256:
                raise BoundaryError("upload", "member_hash_mismatch")
            seen.add(name)
    if seen != set(expected):
        raise BoundaryError("upload", "missing_archive_members")


class UploadService:
    def __init__(
        self, operations: Operations, staging: Staging, store: ArtifactStore, producer: Producer
    ) -> None:
        from .console_index import ConsoleIndex

        self.console_index = ConsoleIndex(operations, initialize=False)
        # Projection storage is optional. Owner operations stay available; console
        # GET fails visibly until an operator repairs/rebuilds the derived index.
        with suppress(Exception):
            self.console_index.initialize()
        self.operations, self.staging, self.store, self.producer = (
            operations,
            staging,
            store,
            producer,
        )

    def intent(self, device: str, value: object) -> dict[str, Any]:
        fields = {"schema", "transfer_manifest", "archive_sha256", "archive_bytes"}
        if isinstance(value, dict) and "delivery_metadata" in value:
            fields.add("delivery_metadata")
        intent = object_fields(value, fields, "upload")
        if intent["schema"] != "stpd/upload-intent-v1":
            raise BoundaryError("upload", "unsupported_intent")
        digest(intent["archive_sha256"], "upload.archive")
        size = intent["archive_bytes"]
        if type(size) is not int or not 0 < size <= MAX_ARCHIVE:
            raise BoundaryError("upload", "archive_size_limit")
        transfer = transfer_from_json(intent["transfer_manifest"])
        row = self.operations.create_upload(
            device, transfer.content_id, transfer.manifest_sha256, intent
        )
        # Do not overwrite an existing verified projection on an idempotent intent replay.
        if row["status"] == "awaiting_upload":
            self._index_collection_status(row["id"], size, "not_indexed")
        url, headers = self.staging.authorize(row["id"], size)
        return {
            "upload_id": row["id"],
            "upload_url": url,
            "upload_method": "PUT",
            "upload_headers": headers,
            "status": row["status"],
        }

    def verify_pending(self, upload_id: str | None = None) -> int:
        count = 0
        for _ in range(1 if upload_id is not None else 16):
            metadata = (
                self.operations.upload(upload_id)
                if upload_id is not None
                else self.operations.pending_upload(time.time())
            )
            if metadata is None:
                break
            if metadata["status"] != "verification_pending" or metadata["retry_at"] > time.time():
                break
            row = self.operations.upload(metadata["id"])
            try:
                self.verify(row)
            except Exception as error:
                code = (
                    error.code
                    if isinstance(error, BoundaryError)
                    else "transport_or_storage_unavailable"
                )
                self.operations.verification_failure(row["id"], code, now=time.time())
            count += 1
        return count

    def verify(self, row: dict[str, Any]) -> dict[str, Any]:
        intent = json.loads(row["intent"])
        transfer = transfer_from_json(intent["transfer_manifest"])
        findings: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "bundle"
            directory.mkdir()
            archive = Path(tmp) / "bundle.tar.gz"
            # Transport failures leave verification pending for a later bounded attempt.
            with archive.open("wb") as target:
                self.staging.download(row["id"], target, intent["archive_bytes"])
            with archive.open("rb") as handle:
                actual = hashlib.file_digest(handle, "sha256").hexdigest()
            try:
                if actual != intent["archive_sha256"]:
                    raise BoundaryError("upload", "archive_hash_mismatch")
                unpack(archive, directory, transfer)
                verification = verify_human_session_bundle(directory)
                if not verification.passed:
                    findings.extend(finding.code for finding in verification.findings)
                    if not findings:
                        findings.append("platform_verification_failed")
                elif verification.require_value().bundle_content_id != transfer.content_id:
                    raise BoundaryError("upload", "bundle_content_identity_mismatch")
            except (ValueError, tarfile.TarError, gzip.BadGzipFile, EOFError, zlib.error) as error:
                findings.append(
                    error.code
                    if isinstance(error, BoundaryError)
                    else "platform_verification_failed"
                )
            receipt: dict[str, Any] = {
                "schema": "stpd/receive-receipt-v1",
                "receipt_id": row["id"],
                "content_id": transfer.content_id,
                "manifest_sha256": transfer.manifest_sha256,
                "status": "quarantined" if findings else "verified",
                "findings": findings,
                "verifier": {
                    "package": "rsgcsg-sts2-platform-evidence",
                    "version": version("rsgcsg-sts2-platform-evidence"),
                    "entrypoint": "verify_human_session_bundle",
                    "source_lock": self.producer.uv_lock_sha256,
                },
            }
            with archive.open("rb") as source:
                raw_payload = self.store.put_payload("archive", source, "application/gzip")
            manifest_payload = self.store.put_payload(
                "transfer", io.BytesIO(json_bytes(transfer.to_dict())), "application/json"
            )
            intent_payload = self.store.put_payload(
                "intent", io.BytesIO(json_bytes(intent)), "application/json"
            )
            receipt_payload = self.store.put_payload(
                "receipt", io.BytesIO(json_bytes(receipt)), "application/json"
            )
            evidence = Manifest(
                "evidence",
                self.producer,
                payloads=(raw_payload, manifest_payload, receipt_payload, intent_payload),
                parameters=FrozenObject.of(
                    {
                        "schema": "stpd/received-bundle-v1",
                        "content_id": transfer.content_id,
                        "disposition": receipt["status"],
                        "research_admission": "not_evaluated",
                    }
                ),
            )
            evidence_id = self.store.publish(evidence)
            receipt["evidence_id"] = evidence_id
            self.operations.finish_upload(row["id"], receipt)
            if findings:
                self._index_collection_status(row["id"], intent["archive_bytes"], "quarantined")
            else:
                try:
                    self.index_verified_bundle(row, verification.require_value())
                except Exception:
                    # A derived presentation failure never rewrites immutable verification.
                    # Its explicit missing state is repaired by the owner console-refresh CLI.
                    self._index_collection_status(row["id"], intent["archive_bytes"], "unavailable")
            return receipt

    def _index_collection_status(self, upload_id: str, size: int, status: str) -> None:
        # Even the failure marker is optional: never mask durable owner outcome.
        with suppress(Exception):
            self.console_index.collection(upload_id, size, None, status=status)

    def index_verified_bundle(
        self,
        row: dict[str, Any],
        bundle: VerifiedHumanSessionBundle,
    ) -> None:
        from sts2_platform_evidence import summarize_verified_human_bundle

        summary = summarize_verified_human_bundle(bundle)
        self.console_index.collection(
            row["id"], json.loads(row["intent"])["archive_bytes"], summary
        )

    def refresh_console(self, *, upload_id: str | None = None) -> dict[str, int]:
        """Explicit owner CLI repair/rebuild; immutable historical receipts stay unchanged."""
        # Unlike background telemetry, this command explicitly requests index repair;
        # surface failures to its operator without changing any receiver receipt.
        self.console_index.initialize()
        indexed = 0
        offset = 0
        while True:
            rows = (
                [self.operations.upload(upload_id)]
                if upload_id
                else self.operations.uploads(limit=100, offset=offset)
            )
            for metadata in rows:
                if metadata["status"] != "verified":
                    continue
                row = self.operations.upload(metadata["id"])
                receipt = json.loads(row["receipt"])
                manifest = self.store.get_manifest(receipt["evidence_id"])
                if manifest.kind != "evidence":
                    raise BoundaryError("console", "received_artifact_kind_mismatch")
                intent = json.loads(row["intent"])
                transfer = transfer_from_json(intent["transfer_manifest"])
                with tempfile.TemporaryDirectory() as tmp:
                    archive, directory = Path(tmp) / "bundle.tar.gz", Path(tmp) / "bundle"
                    directory.mkdir()
                    with archive.open("xb") as target:
                        for chunk in self.store.read_payload(manifest.payload("archive")):
                            target.write(chunk)
                    if manifest.payload("archive").sha256 != intent["archive_sha256"]:
                        raise BoundaryError("console", "archive_identity_mismatch")
                    unpack(archive, directory, transfer)
                    verification = verify_human_session_bundle(directory)
                    bundle = verification.require_value()
                    if bundle.bundle_content_id != row["content_id"]:
                        raise BoundaryError("console", "bundle_content_identity_mismatch")
                    self.index_verified_bundle(row, bundle)
                    indexed += 1
            if upload_id or len(rows) < 100:
                break
            offset += 100
        manifests = 0
        for identity in self.store.manifest_ids():
            self.console_index.artifact(self.store.get_manifest(identity))
            manifests += 1
        return {"collections_indexed": indexed, "manifests_checked": manifests}
