"""Bounded untrusted ingress; exact Platform verification precedes trusted publication."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Protocol

from sts2_platform_evidence import DirectoryTransferManifest, verify_human_session_bundle

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
    expected = {file.path: file for file in transfer.files}
    seen: set[str] = set()
    with tarfile.open(archive, "r|gz") as stream:
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
        url, headers = self.staging.authorize(row["id"], size)
        return {
            "upload_id": row["id"],
            "upload_url": url,
            "upload_method": "PUT",
            "upload_headers": headers,
            "status": row["status"],
        }

    def verify_pending(self) -> int:
        count = 0
        for row in self.operations.uploads():
            if row["status"] != "verification_pending" or row["retry_at"] > time.time():
                continue
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
            except (ValueError, tarfile.TarError) as error:
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
            return receipt
