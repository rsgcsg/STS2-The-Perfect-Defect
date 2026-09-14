"""Project reads and immutable exports preserve evidence, consent and sealed boundaries."""

from __future__ import annotations

import concurrent.futures
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from platform_bundle3_fixture import bundle3
from sts2_platform_evidence import verify_human_session_bundle
from test_hub_console import service

from stpd.artifact_contracts import Manifest, Parent
from stpd.fullrun.data import admit, publish_dataset, publish_source
from stpd.fullrun.fixtures import SyntheticSourceAdapter, synthetic_bundle
from stpd.fullrun.platform_bundle3 import archive_bundle
from stpd.hub.access import require_artifact_access
from stpd.hub.console_auth import ConsolePrincipal
from stpd.hub.console_routes import ConsoleRoutes
from stpd.hub.exports import REQUEST_SCHEMA, ExportService
from stpd.hub.statistics import refresh_decision_statistics
from stpd.json_boundary import BoundaryError, FrozenObject, json_bytes

MEMBER = ConsolePrincipal("member", ("one",), subject="member-subject")
ADMIN = ConsolePrincipal("admin", (), subject="admin-subject")
DEVICE = ConsolePrincipal("collector", ("one",))


def request(*, collections: list[str] | None = None, artifacts: list[dict] | None = None) -> dict:
    return {
        "schema": REQUEST_SCHEMA,
        "collections": collections or [],
        "artifacts": artifacts or [],
    }


def received(
    owner, content: bytes, *, number: int = 1, status: str = "verified", content_id: str = "c" * 64
):
    upload_id = f"{number:032x}"
    payload = owner.store.put_payload("archive", io.BytesIO(content), "application/gzip")
    received = Manifest(
        "evidence",
        owner.producer,
        payloads=(payload,),
        parameters=FrozenObject.of(
            {
                "schema": "stpd/received-bundle-v1",
                "content_id": content_id,
                "disposition": status,
                "research_admission": "not_evaluated",
            }
        ),
    )
    owner.store.publish(received)
    receipt = {"evidence_id": received.artifact_id, "status": status, "content_id": content_id}
    intent = {"archive_sha256": payload.sha256, "archive_bytes": len(content)}
    with owner.operations.transaction() as db:
        db.execute(
            "INSERT INTO uploads(id,device,content_id,manifest_sha,intent,status,receipt) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                upload_id,
                "one",
                content_id,
                "a" * 64,
                json.dumps(intent),
                status,
                json.dumps(receipt),
            ),
        )
    return upload_id, received


def test_members_global_statistics_preserve_coverage_and_device_scope(
    tmp_path: Path, monkeypatch
) -> None:
    owner = service(tmp_path)
    with owner.operations.transaction() as db:
        for i, device, content in ((1, "one", "a"), (2, "two", "a"), (3, "two", "b")):
            db.execute(
                "INSERT INTO uploads(id,device,content_id,manifest_sha,intent,status) "
                "VALUES(?,?,?,?,?,?)",
                (f"{i:032x}", device, content * 64, "b" * 64, "private-invalid-json", "verified"),
            )
    owner.console_index.collection(
        f"{1:032x}",
        1,
        {
            "campaign_id": "campaign",
            "counts": {"canonical": 5, "real_failures": 0, "cancelled": 2},
            "native_starts": 1,
            "native_ends": 1,
        },
    )
    owner.console_index.collection(
        f"{2:032x}", 1, {"counts": {"canonical": 5, "real_failures": None}}
    )
    monkeypatch.setattr(owner.store, "get_manifest", lambda *a: pytest.fail("GET read raw store"))
    monkeypatch.setattr(owner.store, "manifest_ids", lambda *a: pytest.fail("GET scanned store"))
    value = ConsoleRoutes(owner, 0).read("statistics", "", MEMBER)
    assert value["uploads"] == 3 and value["unique_content_ids"] == 2
    assert value["duplicate_content_uploads"] == 1
    assert value["metrics"]["canonical"] == {
        "value": 10,
        "known": 2,
        "unknown": 1,
        "coverage_unit": "upload_occurrences",
        "partial": True,
    }
    assert value["metrics"]["real_failures"]["known"] == 1
    assert value["metrics"]["real_failures"]["value"] == 0
    assert value["metrics"]["diagnostics"]["value"] is None
    assert value["facets"]["action_family"]["availability"] == "unavailable"
    assert value["collection_profiles"]["profiles_missing"] == 3
    assert "private-invalid-json" not in json.dumps(value)
    assert owner.console_index.counts(MEMBER)["collections"] == 3
    assert owner.console_index.counts(DEVICE)["collections"] == 1
    filtered = SimpleNamespace(role="member", research=True, data_device="two", devices=("one",))
    assert owner.console_index.counts(filtered)["collections"] == 2
    assert owner.console_index.counts(ADMIN)["collections"] == 3


@pytest.mark.parametrize("member", [False, True])
def test_sealed_known_ids_and_wrapped_results_blocked(tmp_path: Path, member: bool) -> None:
    owner = service(tmp_path)
    payload = owner.store.put_payload("metrics", io.BytesIO(b"sealed metrics"))
    sealed = Manifest(
        "offline_evaluation",
        owner.producer,
        payloads=(payload,),
        parameters=FrozenObject.of({"partition": "test"}),
    )
    owner.store.publish(sealed)
    wrapped = Manifest(
        "analysis", owner.producer, parents=(Parent("evaluation", sealed.artifact_id),)
    )
    owner.store.publish(wrapped)
    # Publication order does not permit a public wrapper to retain sealed discovery.
    owner.console_index.artifact(wrapped)
    owner.console_index.artifact(sealed)
    owner.console_index.artifact(wrapped)
    assert owner.console_index.artifacts(MEMBER, "models", limit=25, offset=0)["total"] == 0
    for manifest in (sealed, wrapped, Manifest("gold_labels", owner.producer)):
        with pytest.raises(BoundaryError, match="unauthorized"):
            require_artifact_access(manifest, project_member=member, store=owner.store)
    dev = replace(sealed, parameters=FrozenObject.of({"partition": "dev"}))
    owner.store.publish(dev)
    require_artifact_access(dev, project_member=member, payload_role="metrics", store=owner.store)


def test_export_inventory_is_immutable_verified_and_member_only(
    tmp_path: Path, monkeypatch
) -> None:
    owner, content = service(tmp_path), b"exact weights"
    exports = ExportService(owner)
    payload = owner.store.put_payload("weights", io.BytesIO(content))
    manifest = Manifest("model", owner.producer, payloads=(payload,))
    owner.store.publish(manifest)
    selection = request(artifacts=[{"artifact_id": manifest.artifact_id, "roles": ["weights"]}])
    # Inventory construction reads manifests only, never weights or arbitrary store listings.
    with monkeypatch.context() as patcher:
        patcher.setattr(
            owner.store, "read_payload", lambda *a: pytest.fail("packaging during selection")
        )
        patcher.setattr(owner.store, "manifest_ids", lambda: pytest.fail("store scan"))
        first = exports.create(MEMBER, selection)
    second = exports.create(ADMIN, selection)
    assert first == second
    inventory = {k: v for k, v in first.items() if k not in {"export_id", "created_at"}}
    assert hashlib.sha256(json_bytes(inventory)).hexdigest() == first["export_id"]
    for file in first["files"]:
        metadata, stream = exports.payload(MEMBER, first["export_id"], file["file_id"])
        raw = b"".join(stream)
        assert (
            len(raw) == metadata["size"] and hashlib.sha256(raw).hexdigest() == metadata["sha256"]
        )
    with pytest.raises(BoundaryError, match="unauthorized"):
        exports.create(DEVICE, selection)
    with pytest.raises(BoundaryError, match="unauthorized"):
        exports.read(DEVICE, first["export_id"])
    with pytest.raises(BoundaryError, match="file_not_selected"):
        exports.payload(MEMBER, first["export_id"], "f" * 64)
    with owner.operations.transaction() as db:
        db.execute("UPDATE project_exports SET inventory='{}' WHERE id=?", (first["export_id"],))
    with pytest.raises(BoundaryError, match="inventory_integrity_failure"):
        exports.read(MEMBER, first["export_id"])


@pytest.mark.parametrize("status", ["verified", "quarantined"])
def test_raw_archive_requires_explicit_grant_revocable_after_export(
    tmp_path: Path, status: str
) -> None:
    owner = service(tmp_path)
    exports = ExportService(owner)
    upload, manifest = received(owner, b"unmodified original archive", status=status)
    before = owner.operations.upload(upload)
    assert exports.collection_access([upload])[upload]["availability"] == "not_granted"
    with pytest.raises(BoundaryError, match="collection_not_shared"):
        exports.create(MEMBER, request(collections=[upload]))
    exports.set_collection_access(upload, approved=True, evidence_ref="a" * 64, actor="owner")
    result = exports.create(MEMBER, request(collections=[upload]))
    assert result["files_count"] == 1 and result["files"][0]["role"] == "archive"
    assert result["files"][0]["artifact_id"] == manifest.artifact_id
    assert "intent" not in json.dumps(result) and "owner" not in json.dumps(result)
    assert owner.operations.upload(upload) == before
    exports.set_collection_access(upload, approved=False, evidence_ref="b" * 64, actor="owner")
    with pytest.raises(BoundaryError, match="collection_not_shared"):
        exports.payload(MEMBER, result["export_id"], result["files"][0]["file_id"])
    assert owner.operations.upload(upload) == before


def test_export_concurrent_idempotency_bounds_and_no_parent_download(tmp_path: Path) -> None:
    owner = service(tmp_path)
    exports = ExportService(owner)
    parent = Manifest("evidence", owner.producer)
    owner.store.publish(parent)
    model = Manifest("model", owner.producer, parents=(Parent("source", parent.artifact_id),))
    owner.store.publish(model)
    selection = request(artifacts=[{"artifact_id": model.artifact_id, "roles": []}])
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: exports.create(MEMBER, selection), range(4)))
    assert len({item["export_id"] for item in results}) == 1
    assert results[0]["files_count"] == 1
    assert results[0]["files"][0]["artifact_id"] == model.artifact_id
    with pytest.raises(BoundaryError, match="invalid_selection"):
        exports.create(MEMBER, request(collections=["a" * 32] * 101))
    with pytest.raises(BoundaryError):
        exports.create(
            MEMBER, request(artifacts=[{"artifact_id": "https://evil.invalid", "roles": []}])
        )
    with (
        patch("stpd.hub.exports.MAX_BYTES", 1),
        pytest.raises(BoundaryError, match="export_size_limit"),
    ):
        exports.create(MEMBER, selection)


def test_dataset_profile_facts_are_explicit_materialization_not_get(
    tmp_path: Path, monkeypatch
) -> None:
    owner = service(tmp_path)
    source, projection = publish_source(
        owner.store, synthetic_bundle(runs=6), SyntheticSourceAdapter(), owner.producer
    )
    dataset = publish_dataset(owner.store, admit((projection,)), (source,), owner.producer)
    owner.console_index.artifact(dataset)
    before = owner.console_index.statistics(MEMBER)["dataset_profiles"]
    assert before["profiles_available"] == 0 and before["profiles_missing"] == 1
    result = refresh_decision_statistics(owner, dataset_ids=(dataset.artifact_id,))
    assert result["items"][0]["availability"] == "available"
    monkeypatch.setattr(owner.store, "get_manifest", lambda *a: pytest.fail("GET read artifact"))
    after = owner.console_index.statistics(MEMBER)["dataset_profiles"]
    assert after["records"] == len(projection.transitions)
    assert after["facets"]["action_family"]["known"] == len(projection.transitions)
    assert after["facets"]["decision_kind"]["known"] == 0
    assert after["facets"]["game_version"]["unknown"] == len(projection.transitions)
    assert after["partial"] is False


def test_received_projection_profiles_nested_decisions_without_dataset_admission(
    tmp_path: Path,
) -> None:
    owner = service(tmp_path / "hub")
    directory = bundle3(tmp_path / "fixture")
    raw = archive_bundle(directory)
    content_id = verify_human_session_bundle(directory).require_value().bundle_content_id
    upload, _ = received(owner, raw, content_id=content_id)
    before = owner.operations.upload(upload)
    result = refresh_decision_statistics(owner, upload_ids=(upload,))
    assert result["items"][0]["availability"] == "available"
    value = owner.console_index.statistics(MEMBER)["collection_profiles"]
    assert value["records"] == 6
    assert {item["value"] for item in value["facets"]["decision_kind"]["items"]} == {
        "root",
        "nested_selector",
    }
    assert value["facets"]["action_family"]["known"] == 6
    assert owner.operations.upload(upload) == before
    assert owner.console_index.statistics(MEMBER)["dataset_profiles"]["sources"] == 0


def test_dataset_sharing_requires_exact_received_ancestor_grant(tmp_path: Path) -> None:
    owner = service(tmp_path)
    exports = ExportService(owner)
    upload, ancestor = received(owner, b"private archive")
    source = Manifest(
        "evidence",
        owner.producer,
        parents=(Parent("received", ancestor.artifact_id),),
        parameters=FrozenObject.of(
            {"schema": "stpd/source-projection-v1", "scope": "platform_verified"}
        ),
    )
    owner.store.publish(source)
    payload = owner.store.put_payload("records", io.BytesIO(b"private parquet fixture"))
    dataset = Manifest(
        "dataset",
        owner.producer,
        parents=(Parent("source", source.artifact_id),),
        payloads=(payload,),
    )
    owner.store.publish(dataset)
    selection = request(artifacts=[{"artifact_id": dataset.artifact_id, "roles": ["records"]}])
    with pytest.raises(BoundaryError, match="source_sharing_not_established"):
        exports.create(MEMBER, selection)
    exports.set_collection_access(upload, approved=True, evidence_ref="f" * 64, actor="owner")
    result = exports.create(MEMBER, selection)
    assert {item["artifact_id"] for item in result["files"]} == {dataset.artifact_id}
    exports.set_collection_access(upload, approved=False, evidence_ref="e" * 64, actor="owner")
    with pytest.raises(BoundaryError, match="source_sharing_not_established"):
        exports.read(ADMIN, result["export_id"])
    historical_source = replace(source, parents=())
    owner.store.publish(historical_source)
    historical = replace(dataset, parents=(Parent("source", historical_source.artifact_id),))
    owner.store.publish(historical)
    with pytest.raises(BoundaryError, match="source_sharing_not_established"):
        exports.create(
            MEMBER, request(artifacts=[{"artifact_id": historical.artifact_id, "roles": []}])
        )


def test_collection_identity_and_stream_tamper_stay_fail_closed(tmp_path: Path) -> None:
    owner = service(tmp_path)
    exports = ExportService(owner)
    upload, manifest = received(owner, b"archive")
    exports.set_collection_access(upload, approved=True, evidence_ref="a" * 64, actor="owner")
    result = exports.create(MEMBER, request(collections=[upload]))
    file = result["files"][0]
    index_key = f"payload-indexes/v1/{manifest.payload('archive').sha256}.json"
    blobs = owner.store.blobs
    original_get = blobs.get
    with (
        patch.object(
            blobs,
            "get",
            side_effect=lambda key: b"corrupt" if key == index_key else original_get(key),
        ),
        pytest.raises(BoundaryError),
    ):
        b"".join(exports.payload(MEMBER, result["export_id"], file["file_id"])[1])
    with owner.operations.transaction() as db:
        db.execute(
            "UPDATE uploads SET intent=? WHERE id=?",
            (json.dumps({"archive_sha256": "f" * 64, "archive_bytes": 7}), upload),
        )
    with pytest.raises(BoundaryError, match="collection_identity_mismatch"):
        exports.read(MEMBER, result["export_id"])


def test_failed_profile_does_not_reclassify_owner_receipt(tmp_path: Path) -> None:
    owner = service(tmp_path)
    upload, _ = received(owner, b"invalid archive")
    before = owner.operations.upload(upload)
    result = refresh_decision_statistics(owner, upload_ids=(upload,))
    assert result["items"][0]["availability"] == "unavailable"
    assert owner.operations.upload(upload) == before
    stats = owner.console_index.statistics(MEMBER)
    assert stats["collection_profiles"]["records"] is None
    assert stats["collection_profiles"]["profiles_missing"] == 1
    assert stats["metrics"]["real_failures"]["value"] is None
