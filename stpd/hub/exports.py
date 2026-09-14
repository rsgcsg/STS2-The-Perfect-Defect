"""Bounded immutable download inventories, not ZIP jobs or scientific admission.

Every HTTP request authenticates again. Inventories contain exact selected own files,
never storage keys, presigned URLs, credentials, local paths or recursive parent bytes.
Raw collection sharing is an explicit durable owner grant independent of upload consent.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Iterator
from contextlib import closing
from typing import Any

from ..artifact_contracts import Manifest
from ..json_boundary import BoundaryError, digest, json_bytes, object_fields
from .access import POLICY_VERSION, lineage, project_member, require_artifact_access
from .console_auth import ConsolePrincipal
from .console_index import timestamp
from .uploads import UploadService

SCHEMA = "stpd/project-export-v1"
REQUEST_SCHEMA = "stpd/project-export-request-v1"
MAX_SELECTIONS = 100
MAX_FILES = 1000
MAX_BYTES = 20 * 1024**3
MAX_INVENTORY_BYTES = 2 * 1024**2


class ExportService:
    def __init__(self, service: UploadService) -> None:
        self.service = service
        with service.operations.transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS collection_sharing("
                "upload_id TEXT PRIMARY KEY,approved INTEGER NOT NULL,"
                "evidence_ref TEXT NOT NULL,changed_at REAL NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS project_exports("
                "id TEXT PRIMARY KEY,inventory TEXT NOT NULL,created_at REAL NOT NULL)"
            )

    @staticmethod
    def _member(principal: ConsolePrincipal) -> None:
        if not project_member(principal):
            raise BoundaryError("hub", "unauthorized")

    @staticmethod
    def _upload_id(value: object) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
            raise BoundaryError("sharing", "invalid_upload_id")
        return value

    def set_collection_access(
        self,
        upload_id: str,
        *,
        approved: bool,
        evidence_ref: str,
        actor: str,
    ) -> None:
        """Owner operation after explicit scoped approval, not a member HTTP mutation.

        The reference identifies the immutable approval/enrollment evidence. Revocation
        affects future requests without rewriting an export, receipt or archive.
        """
        identity = self._upload_id(upload_id)
        digest(evidence_ref, "sharing.evidence_ref")
        if type(approved) is not bool or not actor or len(actor) > 256:
            raise BoundaryError("sharing", "invalid_approval")
        with self.service.operations.transaction() as db:
            if db.execute("SELECT 1 FROM uploads WHERE id=?", (identity,)).fetchone() is None:
                raise BoundaryError("sharing", "collection_not_found")
            previous = db.execute(
                "SELECT approved,evidence_ref FROM collection_sharing WHERE upload_id=?",
                (identity,),
            ).fetchone()
            if previous and tuple(previous) == (int(approved), evidence_ref):
                return
            db.execute(
                "INSERT INTO collection_sharing VALUES(?,?,?,?) "
                "ON CONFLICT(upload_id) DO UPDATE SET approved=excluded.approved,"
                "evidence_ref=excluded.evidence_ref,changed_at=excluded.changed_at",
                (identity, int(approved), evidence_ref, time.time()),
            )
            self.service.operations._event(
                db,
                actor,
                "collection_sharing_changed",
                identity,
                {"approved": approved, "evidence_ref": evidence_ref},
            )

    def collection_access(self, upload_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Safe page-sized availability only. Download rechecks actual immutable bytes."""
        if len(upload_ids) > MAX_SELECTIONS:
            raise BoundaryError("sharing", "selection_limit")
        result = {}
        with closing(self.service.console_index.read()) as db:
            for identity in upload_ids:
                self._upload_id(identity)
                row = db.execute(
                    "SELECT u.status,s.approved FROM uploads u LEFT JOIN collection_sharing s "
                    "ON s.upload_id=u.id WHERE u.id=?",
                    (identity,),
                ).fetchone()
                reason = "not_granted"
                if row and row[1] == 1:
                    reason = (
                        "available" if row[0] in {"verified", "quarantined"} else "not_received"
                    )
                result[identity] = {"availability": reason, "scope": "project_members"}
        return result

    def _collection(self, upload_id: str) -> Manifest:
        identity = self._upload_id(upload_id)
        with closing(self.service.console_index.read()) as db:
            row = db.execute(
                "SELECT u.*,s.approved FROM uploads u LEFT JOIN collection_sharing s "
                "ON s.upload_id=u.id WHERE u.id=?",
                (identity,),
            ).fetchone()
        if row is None or row["approved"] != 1:
            raise BoundaryError("sharing", "collection_not_shared")
        if row["status"] not in {"verified", "quarantined"} or not row["receipt"]:
            raise BoundaryError("sharing", "collection_not_received")
        receipt = json.loads(row["receipt"])
        manifest = self.service.store.get_manifest(receipt["evidence_id"])
        info = manifest.parameters.value()
        intent = json.loads(row["intent"])
        archive = manifest.payload("archive")
        if (
            manifest.kind != "evidence"
            or info.get("schema") != "stpd/received-bundle-v1"
            or info.get("content_id") != row["content_id"]
            or receipt.get("content_id") != row["content_id"]
            or info.get("disposition") != row["status"]
            or receipt.get("status") != row["status"]
            or archive.sha256 != intent.get("archive_sha256")
            or archive.size != intent.get("archive_bytes")
        ):
            raise BoundaryError("sharing", "collection_identity_mismatch")
        return manifest

    def _artifact(self, artifact_id: str) -> Manifest:
        manifest = self.service.store.get_manifest(digest(artifact_id, "export.artifact_id"))
        require_artifact_access(manifest, project_member=True, store=self.service.store)
        # A derived Dataset exposes Human decision bytes. Its received-source ancestors
        # require the same sharing grants as their archives; model weights do not grant
        # permission to pull source data implicitly.
        if manifest.kind == "dataset":
            for ancestor in lineage(self.service.store, manifest):
                info = ancestor.parameters.value()
                if (
                    info.get("schema") == "stpd/source-projection-v1"
                    and info.get("scope") != "engineering"
                    and not any(
                        node.parameters.value().get("schema") == "stpd/received-bundle-v1"
                        for node in lineage(self.service.store, ancestor)
                    )
                ):
                    raise BoundaryError("sharing", "source_sharing_not_established")
                if info.get("schema") != "stpd/received-bundle-v1":
                    continue
                with closing(self.service.console_index.read()) as db:
                    rows = db.execute(
                        "SELECT id FROM uploads WHERE json_extract(receipt,'$.evidence_id')=?",
                        (ancestor.artifact_id,),
                    ).fetchall()
                if not rows:
                    raise BoundaryError("sharing", "source_sharing_not_established")
                # Identical data received by another device is not a grant for this
                # immutable received-source artifact; the exact parent must be shared.
                shared = False
                for row in rows:
                    try:
                        shared = self._collection(row[0]).artifact_id == ancestor.artifact_id
                    except BoundaryError as error:
                        if error.code != "collection_not_shared":
                            raise
                    if shared:
                        break
                if not shared:
                    raise BoundaryError("sharing", "source_sharing_not_established")
        return manifest

    @staticmethod
    def _file(manifest: Manifest, role: str | None, upload_id: str | None = None) -> dict[str, Any]:
        kind = "manifest" if role is None else "payload"
        identity = hashlib.sha256(json_bytes([manifest.artifact_id, kind, role])).hexdigest()
        if role is None:
            raw = manifest.to_bytes()
            size, sha, media = len(raw), hashlib.sha256(raw).hexdigest(), "application/json"
        else:
            item = manifest.payload(role)
            size, sha, media = item.size, item.sha256, item.media_type
        return {
            "file_id": identity,
            "artifact_id": manifest.artifact_id,
            "type": kind,
            "role": role,
            "sha256": sha,
            "size": size,
            "media_type": media,
            "filename": identity + (".json" if role is None else ".bin"),
            "upload_id": upload_id,
        }

    def create(self, principal: ConsolePrincipal, request: object) -> dict[str, Any]:
        self._member(principal)
        value = object_fields(request, {"schema", "collections", "artifacts"}, "export")
        collections, artifacts = value["collections"], value["artifacts"]
        if (
            value["schema"] != REQUEST_SCHEMA
            or not isinstance(collections, list)
            or not isinstance(artifacts, list)
            or not 1 <= len(collections) + len(artifacts) <= MAX_SELECTIONS
        ):
            raise BoundaryError("export", "invalid_selection")
        collections = sorted(self._upload_id(item) for item in collections)
        if len(set(collections)) != len(collections):
            raise BoundaryError("export", "duplicate_selection")
        selected: list[dict[str, Any]] = []
        files: list[dict[str, Any]] = []
        seen: set[str] = set()
        for upload_id in collections:
            manifest = self._collection(upload_id)
            # The original archive contains its own bundle manifest. Transport intent,
            # receiver receipt and arbitrary received-artifact metadata are not exported.
            files.append(self._file(manifest, "archive", upload_id))
        for raw in artifacts:
            item = object_fields(raw, {"artifact_id", "roles"}, "export.artifact")
            manifest = self._artifact(item["artifact_id"])
            roles = item["roles"]
            if (
                not isinstance(roles, list)
                or len(roles) > MAX_FILES
                or any(not isinstance(role, str) for role in roles)
                or len(set(roles)) != len(roles)
                or manifest.artifact_id in seen
            ):
                raise BoundaryError("export", "invalid_payload_roles")
            seen.add(manifest.artifact_id)
            selected.append({"artifact_id": manifest.artifact_id, "roles": sorted(roles)})
            files.append(self._file(manifest, None))
            files.extend(self._file(manifest, role) for role in sorted(roles))
        files.sort(key=lambda item: item["file_id"])
        if len({item["file_id"] for item in files}) != len(files):
            raise BoundaryError("export", "duplicate_file_selection")
        size = sum(item["size"] for item in files)
        if len(files) > MAX_FILES or size > MAX_BYTES:
            raise BoundaryError("export", "export_size_limit")
        inventory = {
            "schema": SCHEMA,
            "policy": POLICY_VERSION,
            "selection": {
                "collections": collections,
                "artifacts": sorted(selected, key=lambda item: item["artifact_id"]),
            },
            "files": files,
            "total_bytes": size,
            "files_count": len(files),
            "scope": "selected_own_payloads",
            "non_claims": ["complete lineage cache", "research admission", "training permission"],
        }
        raw_bytes = json_bytes(inventory)
        if len(raw_bytes) > MAX_INVENTORY_BYTES:
            raise BoundaryError("export", "inventory_size_limit")
        identity = hashlib.sha256(raw_bytes).hexdigest()
        with self.service.operations.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO project_exports VALUES(?,?,?)",
                (identity, raw_bytes.decode(), time.time()),
            )
            self.service.operations._event(
                db,
                principal.subject,
                "project_export_selected",
                identity,
                {"files": len(files), "bytes": size},
            )
        return self.read(principal, identity)

    def _inventory(self, principal: ConsolePrincipal, export_id: str) -> dict[str, Any]:
        self._member(principal)
        identity = digest(export_id, "export.id")
        with closing(self.service.console_index.read()) as db:
            row = db.execute(
                "SELECT inventory,created_at FROM project_exports WHERE id=?",
                (identity,),
            ).fetchone()
        if row is None:
            raise BoundaryError("export", "export_not_found")
        raw = row[0].encode()
        if len(raw) > MAX_INVENTORY_BYTES or hashlib.sha256(raw).hexdigest() != identity:
            raise BoundaryError("export", "inventory_integrity_failure")
        value = json.loads(raw)
        if value["schema"] != SCHEMA or value["policy"] != POLICY_VERSION:
            raise BoundaryError("export", "export_policy_changed")
        return {**value, "export_id": identity, "created_at": timestamp(row[1])}

    def read(self, principal: ConsolePrincipal, export_id: str) -> dict[str, Any]:
        value = self._inventory(principal, export_id)
        # No cached capability: current consent and sealed boundaries are rechecked.
        for upload_id in value["selection"]["collections"]:
            self._collection(upload_id)
        for item in value["selection"]["artifacts"]:
            self._artifact(item["artifact_id"])
        return value

    def payload(
        self,
        principal: ConsolePrincipal,
        export_id: str,
        file_id: str,
    ) -> tuple[dict[str, Any], Iterator[bytes]]:
        value = self._inventory(principal, export_id)
        identity = digest(file_id, "export.file_id")
        item = next((item for item in value["files"] if item["file_id"] == identity), None)
        if item is None:
            raise BoundaryError("export", "file_not_selected")
        # Recheck the requested file, not every other source in a bulk selection on
        # every streamed download. Inventory retrieval separately checks the full set.
        manifest = (
            self._collection(item["upload_id"])
            if item["upload_id"]
            else self._artifact(item["artifact_id"])
        )
        observed = self._file(manifest, item["role"], item["upload_id"])
        if item != observed:
            raise BoundaryError("export", "file_identity_mismatch")
        if item["type"] == "manifest":
            return item, iter((manifest.to_bytes(),))
        # The ArtifactStore verifies every bounded chunk and the final size/hash. The
        # client also verifies the inventory hash and whole file before publishing it.
        return item, self.service.store.read_payload(manifest.payload(item["role"]))
