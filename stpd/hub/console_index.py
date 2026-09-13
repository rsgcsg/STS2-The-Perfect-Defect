"""Rebuildable console projections, written by owners and never rebuilt on HTTP GET."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

from ..artifact_contracts import Manifest
from ..json_boundary import BoundaryError
from ..storage.store import ArtifactStore
from .access import RESULT_KINDS
from .console_auth import ConsolePrincipal
from .database import Operations

SCHEMA = "stpd/console-v1"
ARTIFACT_KINDS = RESULT_KINDS | {"dataset"}
STATUSES = frozenset(
    {"awaiting_upload", "verification_pending", "verified", "quarantined", "transfer_failed"}
)


def timestamp(value: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if value is None else value, UTC).isoformat()


def pagination(raw: str) -> tuple[int, int, str | None]:
    try:
        query = parse_qs(raw, strict_parsing=True, keep_blank_values=True, max_num_fields=3)
        if set(query) - {"limit", "offset", "status"} or any(len(v) != 1 for v in query.values()):
            raise ValueError
        limit, offset = int(query.get("limit", ["25"])[0]), int(query.get("offset", ["0"])[0])
        status = query.get("status", [None])[0]
        if not 1 <= limit <= 100 or not 0 <= offset <= 1_000_000:
            raise ValueError
        if status is not None and status not in STATUSES:
            raise ValueError
        return limit, offset, status
    except ValueError:
        raise BoundaryError("console", "invalid_pagination") from None


def envelope(items: list[dict[str, Any]], total: int, limit: int, offset: int) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "observed_at": timestamp(),
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < total else None,
    }


class ConsoleIndex:
    def __init__(self, operations: Operations) -> None:
        self.operations = operations
        with operations.transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS console_collections("
                "upload_id TEXT PRIMARY KEY, archive_bytes INTEGER, summary TEXT, "
                "summary_status TEXT NOT NULL, indexed_at REAL NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS console_artifacts("
                "artifact_id TEXT PRIMARY KEY, kind TEXT NOT NULL, summary TEXT NOT NULL, "
                "indexed_at REAL NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS console_lineage("
                "child TEXT NOT NULL,parent TEXT NOT NULL,PRIMARY KEY(child,parent))"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS console_lineage_parent ON console_lineage(parent)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS console_artifact_kind "
                "ON console_artifacts(kind,indexed_at)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS console_event_subject "
                "ON events(subject,operation,sequence)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS console_upload_device ON uploads(device)")

    def collection(
        self,
        upload_id: str,
        archive_bytes: int | None,
        summary: dict[str, Any] | None,
        *,
        status: str = "available",
    ) -> None:
        if status not in {"available", "not_indexed", "unavailable", "quarantined"}:
            raise BoundaryError("console", "invalid_summary_status")
        with self.operations.transaction() as db:
            db.execute(
                "INSERT INTO console_collections VALUES(?,?,?,?,?) "
                "ON CONFLICT(upload_id) DO UPDATE SET archive_bytes=excluded.archive_bytes, "
                "summary=excluded.summary,summary_status=excluded.summary_status, "
                "indexed_at=excluded.indexed_at",
                (
                    upload_id,
                    archive_bytes,
                    json.dumps(summary) if summary is not None else None,
                    status,
                    time.time(),
                ),
            )

    def artifact(self, manifest: Manifest) -> None:
        with self.operations.transaction() as db:
            db.executemany(
                "INSERT OR IGNORE INTO console_lineage VALUES(?,?)",
                [(manifest.artifact_id, parent.artifact_id) for parent in manifest.parents],
            )
        if manifest.kind not in ARTIFACT_KINDS:
            return
        parameters = manifest.parameters.value()
        if manifest.kind == "offline_evaluation" and parameters.get("partition") == "test":
            # Preserve the research owner's sealed-evaluation discovery boundary.
            with self.operations.transaction() as db:
                db.execute(
                    "DELETE FROM console_artifacts WHERE artifact_id=?", (manifest.artifact_id,)
                )
            return
        # No arbitrary parameters, labels, metrics or payload descriptors cross the boundary.
        # This explicitly excludes sealed test/Gold content even inside result parameters.
        summary = {
            "artifact_id": manifest.artifact_id,
            "id": manifest.artifact_id,
            "kind": manifest.kind,
            "producer": manifest.producer.to_dict(),
            "parents": [parent.to_dict() for parent in manifest.parents],
            "metadata": {
                key: parameters[key]
                for key in ("schema", "scope", "records")
                if key in parameters and isinstance(parameters[key], (str, int))
            },
            "payload_bytes": sum(payload.size for payload in manifest.payloads),
            "metrics": {"status": "not_exposed"},
        }
        with self.operations.transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO console_artifacts VALUES(?,?,?,?)",
                (manifest.artifact_id, manifest.kind, json.dumps(summary), time.time()),
            )

    def artifact_closure(self, store: ArtifactStore, identities: tuple[str, ...]) -> int:
        """Owner publication hook or explicit CLI only; never called from GET."""
        pending = list(identities)
        seen: set[str] = set()
        while pending:
            identity = pending.pop()
            if identity in seen:
                continue
            if len(seen) >= 10000:
                raise BoundaryError("console", "artifact_index_closure_limit")
            manifest = store.get_manifest(identity)
            self.artifact(manifest)
            seen.add(identity)
            pending.extend(parent.artifact_id for parent in manifest.parents)
        return len(seen)

    def read(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.operations.path.resolve().as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        return db

    @staticmethod
    def _scope(principal: ConsolePrincipal, alias: str = "u") -> tuple[str, tuple[str, ...]]:
        return f"{alias}.device IN ({','.join('?' for _ in principal.devices)})", principal.devices

    @staticmethod
    def _collection(row: sqlite3.Row) -> dict[str, Any]:
        from .application import HubApplication

        value = dict(row)
        result = HubApplication.upload_status(value)
        receipt = result["receipt"]
        result.update(
            {
                "id": value["id"],
                "device_id": value["device"],
                "evidence_id": receipt.get("evidence_id") if receipt else None,
                "archive_bytes": value["archive_bytes"],
                "created_at": timestamp(value["created_at"]) if value["created_at"] else None,
                "receipt_at": timestamp(value["verified_at"]) if value["verified_at"] else None,
                "verified_at": (
                    timestamp(value["verified_at"])
                    if value["verified_at"] and value["status"] == "verified"
                    else None
                ),
                "summary": json.loads(value["summary"]) if value["summary"] else None,
                "summary_status": value["summary_status"] or "not_indexed",
                "research": {"status": "not_assessed", "scope": "explicit_input_set_required"},
            }
        )
        return result

    def collections(
        self,
        principal: ConsolePrincipal,
        *,
        limit: int,
        offset: int,
        status: str | None = None,
        upload_id: str | None = None,
    ) -> dict[str, Any]:
        where, values = self._scope(principal)
        if status:
            where += " AND u.status=?"
            values += (status,)
        if upload_id:
            where += " AND u.id=?"
            values += (upload_id,)
        query = (
            "SELECT u.id,u.device,u.content_id,u.status,u.receipt,u.retry_at,u.verify_attempts,"
            "u.last_error,c.archive_bytes,c.summary,c.summary_status,"
            "(SELECT MIN(at) FROM events e WHERE e.subject=u.id AND e.operation='upload_created') "
            "AS created_at,"
            "(SELECT MAX(at) FROM events e WHERE e.subject=u.id AND e.operation='upload_receipt') "
            "AS verified_at FROM uploads u LEFT JOIN console_collections c ON c.upload_id=u.id "
            "WHERE " + where
        )
        with closing(self.read()) as db:
            total = db.execute("SELECT COUNT(*) FROM uploads u WHERE " + where, values).fetchone()[
                0
            ]
            rows = db.execute(
                query + " ORDER BY u.rowid DESC LIMIT ? OFFSET ?", (*values, limit, offset)
            ).fetchall()
            result = envelope([self._collection(row) for row in rows], total, limit, offset)
            if upload_id:
                if not rows:
                    raise BoundaryError("console", "collection_not_found")
                events = db.execute(
                    "SELECT sequence,at,operation FROM events WHERE subject=? "
                    "ORDER BY sequence DESC LIMIT 101",
                    (upload_id,),
                ).fetchall()
                result["item"] = result.pop("items")[0]
                result["item"]["timeline"] = [
                    {
                        "sequence": row["sequence"],
                        "at": timestamp(row["at"]),
                        "operation": row["operation"],
                        "clock": "hub",
                    }
                    for row in reversed(events[:100])
                ]
                result["item"]["timeline_truncated"] = len(events) > 100
                item = result["item"]
                if principal.research and item["evidence_id"]:
                    descendants = db.execute(
                        "WITH RECURSIVE downstream(id) AS (SELECT ? UNION "
                        "SELECT child FROM console_lineage JOIN downstream "
                        "ON parent=id LIMIT 10001) "
                        "SELECT a.artifact_id FROM downstream JOIN console_artifacts a "
                        "ON a.artifact_id=downstream.id WHERE a.kind='dataset' LIMIT 101",
                        (item["evidence_id"],),
                    ).fetchall()
                    item["research"]["dataset_ids"] = [value[0] for value in descendants[:100]]
                    item["research"]["lineage_scope"] = "indexed_manifests_only"
                    item["research"]["links_truncated"] = len(descendants) > 100
                    if descendants:
                        item["research"]["status"] = "dataset_references_present"
            return result

    def counts(self, principal: ConsolePrincipal) -> dict[str, Any]:
        where, values = self._scope(principal)
        with closing(self.read()) as db:
            rows = db.execute(
                "SELECT status,COUNT(*) FROM uploads u WHERE " + where + " GROUP BY status", values
            ).fetchall()
            statuses = {str(row[0]): int(row[1]) for row in rows}
            quality = db.execute(
                "SELECT COUNT(c.summary),SUM(json_extract(c.summary,'$.counts.canonical')),"
                "SUM(json_extract(c.summary,'$.counts.real_failures')),"
                "COUNT(json_extract(c.summary,'$.counts.canonical')),"
                "COUNT(json_extract(c.summary,'$.counts.real_failures')) FROM uploads u "
                "LEFT JOIN console_collections c ON c.upload_id=u.id WHERE " + where,
                values,
            ).fetchone()
        return {
            "collections": sum(statuses.values()),
            "statuses": statuses,
            "quality": {
                "summaries_available": quality[0],
                "summaries_missing": sum(statuses.values()) - quality[0],
                "canonical": quality[1],
                "real_failures": quality[2],
                "canonical_known": quality[3],
                "real_failures_known": quality[4],
            },
        }

    def artifacts(
        self,
        principal: ConsolePrincipal,
        kind: str,
        *,
        limit: int,
        offset: int,
        artifact_id: str | None = None,
    ) -> dict[str, Any]:
        if kind == "datasets" and not principal.research:
            return {**envelope([], 0, limit, offset), "availability": "not_authorized"}
        kinds = ("dataset",) if kind == "datasets" else tuple(sorted(RESULT_KINDS))
        marks = ",".join("?" for _ in kinds)
        where = "kind IN (" + marks + ")"
        values = kinds
        if artifact_id:
            where += " AND artifact_id=?"
            values += (artifact_id,)
        with closing(self.read()) as db:
            total = db.execute(
                "SELECT COUNT(*) FROM console_artifacts WHERE " + where, values
            ).fetchone()[0]
            rows = db.execute(
                "SELECT summary,indexed_at FROM console_artifacts WHERE "
                + where
                + " ORDER BY indexed_at DESC,artifact_id LIMIT ? OFFSET ?",
                (*values, limit, offset),
            ).fetchall()
            items = []
            for row in rows:
                item = json.loads(row["summary"])
                # Lineage IDs are useful only under the same metadata permission as their node.
                permitted_kinds = ARTIFACT_KINDS if principal.research else RESULT_KINDS
                parents = []
                for parent in item["parents"]:
                    found = db.execute(
                        "SELECT kind FROM console_artifacts WHERE artifact_id=?",
                        (parent["artifact_id"],),
                    ).fetchone()
                    if found and found[0] in permitted_kinds:
                        parents.append(parent)
                item["lineage_partial"] = len(parents) != len(item["parents"])
                item["parents"] = parents
                item["indexed_at"] = timestamp(row["indexed_at"])
                items.append(item)
        if artifact_id and not items:
            raise BoundaryError("console", "resource_not_found")
        return {
            **envelope(items, total, limit, offset),
            **({"item": items[0]} if artifact_id else {}),
            "availability": "available",
            "index_scope": "owner_publication_and_explicit_refresh",
        }

    def health(self) -> dict[str, Any]:
        with closing(self.read()) as db:
            counts = {
                row[0]: row[1]
                for row in db.execute(
                    "SELECT summary_status,COUNT(*) FROM console_collections "
                    "GROUP BY summary_status"
                )
            }
            last = db.execute(
                "SELECT at FROM events WHERE operation='artifact_index_unavailable' "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        return {
            "collection_summaries": counts,
            "last_artifact_index_issue_at": timestamp(last[0]) if last else None,
            "recovery": "operator_console_refresh_after_owning_fix",
        }

    def jobs(self, *, limit: int, offset: int) -> dict[str, Any]:
        with closing(self.read()) as db:
            total = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            rows = db.execute(
                "SELECT id,kind,input_id,status,max_seconds,reserved_units,attempt_id,result "
                "FROM jobs ORDER BY rowid DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            result = json.loads(item.pop("result")) if row["result"] else None
            # Only immutable result refs and owner states; no worker paths, tokens or metrics.
            item["result"] = (
                {
                    key: value
                    for key, value in (result or {}).items()
                    if key in {"state", "output_id", "checkpoint_id", "result_id"}
                    and isinstance(value, str)
                    and re.fullmatch(r"[a-z0-9_]{1,64}", value)
                }
                if result
                else None
            )
            items.append(item)
        return envelope(items, total, limit, offset)
