"""Explicit, bounded research-owner profiles; HTTP reads only persisted aggregates."""

from __future__ import annotations

import json
import time
from collections import Counter
from contextlib import closing
from typing import TYPE_CHECKING, Any

from ..fullrun.contracts import ResearchTransitionV1, ResearchTransitionV2
from ..json_boundary import BoundaryError, digest
from .access import project_member, require_artifact_access

if TYPE_CHECKING:
    from .console_auth import ConsolePrincipal
    from .console_index import ConsoleIndex
    from .uploads import UploadService

PROFILE_SCHEMA = "stpd/decision-statistics-v1"
DIMENSIONS = (
    "action_family",
    "surface",
    "decision_kind",
    "character",
    "difficulty",
    "game_version",
)
MAX_PROFILE_BYTES = 256 * 1024**2


def decision_profile(records: tuple[ResearchTransitionV1, ...]) -> dict[str, Any]:
    """Facts from verified research projection, never proof of Dataset admission."""
    counts: dict[str, Counter[Any]] = {name: Counter() for name in DIMENSIONS}
    for record in records:
        run = record.state.run.value()
        values = {
            "action_family": record.family,
            "surface": record.surface,
            "decision_kind": (
                record.occurrence.value()["decision_kind"]
                if isinstance(record, ResearchTransitionV2)
                else None
            ),
            "character": run.get("character"),
            "difficulty": run.get("ascension"),
            # EvidenceLink has an environment identity digest, not a version string.
            "game_version": None,
        }
        for name, value in values.items():
            if name == "difficulty":
                valid = type(value) is int and value >= 0
            else:
                valid = isinstance(value, str) and 0 < len(value) <= 128
            if valid:
                counts[name][value] += 1
    return {
        "schema": PROFILE_SCHEMA,
        "records": len(records),
        "facets": {
            name: {
                "known": sum(counter.values()),
                "unknown": len(records) - sum(counter.values()),
                "items": [
                    {"value": key, "count": count}
                    for key, count in sorted(counter.items(), key=lambda item: str(item[0]))
                ],
            }
            for name, counter in counts.items()
        },
        "non_claims": ["all accepted inputs", "Dataset admission", "unique cross-source records"],
    }


def _persist(
    service: UploadService,
    subject: str,
    kind: str,
    source_id: str,
    profile: dict[str, Any],
) -> None:
    with service.operations.transaction() as db:
        db.execute(
            "INSERT INTO console_decision_profiles VALUES(?,?,?,?,?) "
            "ON CONFLICT(subject,kind) DO UPDATE SET source_id=excluded.source_id,"
            "profile=excluded.profile,indexed_at=excluded.indexed_at",
            (subject, kind, source_id, json.dumps(profile), time.time()),
        )


def refresh_decision_statistics(
    service: UploadService,
    *,
    upload_ids: tuple[str, ...] = (),
    dataset_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Owner CLI/worker only. A failed projection stays explicitly unavailable.

    At most ten selected sources, each at most 256 MiB encoded, per invocation. This
    operation does not publish sources/Datasets, reclassify verification or read Gold.
    """
    from ..fullrun.data import load_dataset
    from ..fullrun.platform_bundle3 import PlatformBundle3SourceAdapter

    if not 1 <= len(upload_ids) + len(dataset_ids) <= 10:
        raise BoundaryError("statistics", "selection_limit")
    for identity in upload_ids:
        digest(identity, "statistics.upload_id", length=32)
    for identity in dataset_ids:
        digest(identity, "statistics.dataset_id")
    if len(set(upload_ids)) != len(upload_ids) or len(set(dataset_ids)) != len(dataset_ids):
        raise BoundaryError("statistics", "duplicate_selection")
    result = []
    for kind, identities in (("collection", upload_ids), ("dataset", dataset_ids)):
        for identity in identities:
            source_id = identity
            try:
                if kind == "collection":
                    row = service.operations.upload(identity)
                    if row["status"] != "verified" or not row["receipt"]:
                        raise BoundaryError("statistics", "collection_not_verified")
                    received = service.store.get_manifest(json.loads(row["receipt"])["evidence_id"])
                    info = received.parameters.value()
                    if (
                        received.kind != "evidence"
                        or info.get("schema") != "stpd/received-bundle-v1"
                        or info.get("content_id") != row["content_id"]
                        or info.get("disposition") != "verified"
                    ):
                        raise BoundaryError("statistics", "collection_identity_mismatch")
                    payload = received.payload("archive")
                    source_id = received.artifact_id
                    intent = json.loads(row["intent"])
                    if payload.sha256 != intent["archive_sha256"]:
                        raise BoundaryError("statistics", "collection_identity_mismatch")
                    if payload.size > MAX_PROFILE_BYTES:
                        raise BoundaryError("statistics", "source_size_limit")
                    source = b"".join(service.store.read_payload(payload))
                    projection = PlatformBundle3SourceAdapter().project(source)
                    if projection.accounting.value().get("bundle_content_id") != row["content_id"]:
                        raise BoundaryError("statistics", "collection_identity_mismatch")
                    profile = decision_profile(projection.transitions)
                    profile.update(
                        adapter=projection.adapter_id,
                        source_sha256=payload.sha256,
                        scope="source_projection",
                        admission="not_evaluated",
                    )
                else:
                    manifest = service.store.get_manifest(identity)
                    require_artifact_access(manifest, project_member=True, store=service.store)
                    if (
                        manifest.kind != "dataset"
                        or sum(item.size for item in manifest.payloads) > MAX_PROFILE_BYTES
                    ):
                        raise BoundaryError("statistics", "dataset_size_or_kind_limit")
                    manifest, dataset = load_dataset(service.store, identity)
                    profile = decision_profile(dataset.records)
                    profile.update(scope=dataset.scope, admission="owner_dataset_verified")
                _persist(
                    service, identity, kind, source_id, {"availability": "available", **profile}
                )
                result.append({"id": identity, "kind": kind, "availability": "available"})
            except (ValueError, OSError) as error:
                # Preserve the owning verification result; this is only a failed derived profile.
                code = error.code if isinstance(error, BoundaryError) else "projection_unavailable"
                _persist(
                    service,
                    identity,
                    kind,
                    source_id,
                    {"availability": "unavailable", "reason": code},
                )
                result.append(
                    {"id": identity, "kind": kind, "availability": "unavailable", "reason": code}
                )
    return {"schema": PROFILE_SCHEMA, "items": result}


def profile_summary(index: ConsoleIndex, principal: ConsolePrincipal, kind: str) -> dict[str, Any]:
    if kind == "dataset" and not (project_member(principal) or principal.research):
        return {"availability": "not_authorized"}
    where, values = index._scope(principal)
    if kind == "collection":
        joined = (
            " FROM uploads u LEFT JOIN console_decision_profiles p "
            "ON p.subject=u.id AND p.kind='collection' WHERE " + where
        )
    else:
        joined = (
            " FROM console_artifacts a LEFT JOIN console_decision_profiles p "
            "ON p.subject=a.artifact_id AND p.kind='dataset' WHERE a.kind='dataset'"
        )
        values = ()
    with closing(index.read()) as db:
        total, available, records = db.execute(
            "SELECT COUNT(*),SUM(CASE WHEN json_extract(p.profile,'$.availability')='available' "
            "THEN 1 ELSE 0 END),SUM(json_extract(p.profile,'$.records'))" + joined,
            values,
        ).fetchone()
        available = available or 0
        facets = {}
        for name in DIMENSIONS:
            path = "$.facets." + name
            coverage = db.execute(
                "SELECT SUM(json_extract(p.profile,?)),SUM(json_extract(p.profile,?))" + joined,
                (path + ".known", path + ".unknown", *values),
            ).fetchone()
            # A JSON aggregate is bounded by the persisted owner profile; no raw payload or
            # store listing is touched. Cap high-cardinality UI output and expose truncation.
            rows = db.execute(
                "SELECT json_extract(j.value,'$.value'),SUM(json_extract(j.value,'$.count')) "
                + joined.replace(" WHERE ", ",json_each(p.profile,?) j WHERE ", 1)
                + " GROUP BY json_extract(j.value,'$.value') ORDER BY 2 DESC,1 LIMIT 101",
                (path + ".items", *values),
            ).fetchall()
            facets[name] = {
                "availability": "available" if coverage[0] else "unavailable",
                "known": coverage[0],
                "unknown": coverage[1],
                "items": [{"value": row[0], "count": row[1]} for row in rows[:100]],
                "truncated": len(rows) > 100,
                "unit": "projected_record_occurrences"
                if kind == "collection"
                else "dataset_record_occurrences",
            }
    return {
        "availability": "available" if available else "unavailable",
        "sources": total,
        "profiles_available": available,
        "profiles_missing": total - available,
        "records": records,
        "partial": available < total,
        "facets": facets,
        "scope": "projected_canonical_records" if kind == "collection" else "indexed_datasets",
        "non_claims": [
            "cross-source deduplication",
            "exhaustive input coverage",
            "training permission",
        ],
    }
