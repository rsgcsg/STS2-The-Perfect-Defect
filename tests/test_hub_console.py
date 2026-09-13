"""Actual signed browser JWT, scoped projection and immutable-refresh regressions."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from stpd.artifact_contracts import Manifest, Parent, Producer
from stpd.hub.application import HubApplication
from stpd.hub.console_auth import AccessVerifier, ConsolePrincipal, configured_access
from stpd.hub.console_index import ConsoleIndex, pagination
from stpd.hub.database import Operations
from stpd.hub.uploads import LocalStaging, UploadService
from stpd.json_boundary import BoundaryError, FrozenObject
from stpd.storage.local import LocalBlobStore
from stpd.storage.store import ManifestArtifactStore

ISSUER = "https://test-team.cloudflareaccess.com"
AUDIENCE = "a" * 64


@pytest.fixture
def signed() -> Any:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public.update(kid="test-key", use="sig")
    calls: list[int] = []

    def fetch() -> dict:
        calls.append(1)
        return {"keys": [public]}

    verifier = AccessVerifier(
        ISSUER,
        AUDIENCE,
        [
            {
                "email": "owner@example.org",
                "subject": "known-subject",
                "role": "operator",
                "devices": ["one", "two"],
            },
            {"email": "collector@example.org", "role": "collector", "devices": ["one"]},
        ],
        fetch_keys=fetch,
    )

    def token(**overrides: Any) -> str:
        claims = {
            "iss": ISSUER,
            "aud": [AUDIENCE],
            "iat": int(time.time()) - 1,
            "exp": int(time.time()) + 60,
            "sub": "known-subject",
            "type": "app",
            "email": "owner@example.org",
        }
        claims.update(overrides)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})

    return verifier, token, calls


def service(tmp_path: Path) -> UploadService:
    ops = Operations(tmp_path / "operations.sqlite")
    ops.register("one", "one" * 16)
    ops.register("two", "two" * 16)
    return UploadService(
        ops,
        LocalStaging(tmp_path / "stage", "http://127.0.0.1:8765"),
        ManifestArtifactStore(LocalBlobStore(tmp_path / "store")),
        Producer("test", "a" * 40, "b" * 64),
    )


def call(
    app: HubApplication,
    path: str,
    *,
    token: str = "",
    bearer: str = "",
    method: str = "GET",
    query: str = "",
    headers: dict | None = None,
) -> tuple[str, Any]:
    statuses: list[str] = []
    result = b"".join(
        app(
            {
                "REQUEST_METHOD": method,
                "PATH_INFO": path,
                "QUERY_STRING": query,
                "HTTP_CF_ACCESS_JWT_ASSERTION": token,
                "HTTP_AUTHORIZATION": "Bearer " + bearer,
                "wsgi.input": io.BytesIO(),
                **(headers or {}),
            },
            lambda status, values: statuses.append(status),
        )
    )
    try:
        return statuses[0], json.loads(result)
    except ValueError:
        return statuses[0], result


def test_access_verifies_signature_claims_subject_and_negative_cache(signed: Any) -> None:
    verifier, token, calls = signed
    assert verifier.authenticate(token()).role == "operator"
    assert verifier.authenticate(token(email="COLLECTOR@example.org")).devices == ("one",)
    for overrides in (
        {"exp": 1},
        {"iss": "https://evil.invalid"},
        {"aud": "b" * 64},
        {"iat": int(time.time()) + 500},
        {"nbf": int(time.time()) + 500},
        {"email": "other@example.org"},
        {"sub": "other"},
        {"type": "org"},
    ):
        with pytest.raises(BoundaryError, match="unauthorized"):
            verifier.authenticate(token(**overrides))
    forged = jwt.encode(
        {"email": "owner@example.org"}, "fake" * 16, algorithm="HS256", headers={"kid": "test-key"}
    )
    for value in (forged, "", token()[:-5] + "WRONG", "x" * 16385):
        with pytest.raises(BoundaryError, match="unauthorized"):
            verifier.authenticate(value)
    assert len(calls) == 1


def test_console_origin_bypass_and_device_secrets_cannot_auth_browser(
    tmp_path: Path,
    signed: Any,
) -> None:
    verifier, token, _ = signed
    app = HubApplication(service(tmp_path), "admin" * 16, browser_access=verifier)
    for path in ("/app", "/app/", "/app/assets/console.js", "/app/api/overview"):
        assert (
            call(
                app,
                path,
                bearer="admin" * 16,
                headers={"HTTP_CF_ACCESS_AUTHENTICATED_USER_EMAIL": "owner@example.org"},
            )[0]
            == "401 Unauthorized"
        )
    assert call(app, "/app/api/overview", token=token())[0] == "200 OK"
    assert (
        call(app, "/app/api/overview", token=token(), method="POST")[0] == "405 Method Not Allowed"
    )
    assert call(app, "/v1/console/overview", token=token())[0] == "401 Unauthorized"
    assert call(app, "/v1/console/overview", bearer="one" * 16)[0] == "200 OK"
    disabled = HubApplication(app.service, "admin" * 16)
    assert call(disabled, "/app/api/overview", token=token())[0] == "503 Service Unavailable"
    assert call(disabled, "/health")[0] == "200 OK"


def test_scoped_summary_pagination_never_reads_intent_or_raw_store(
    tmp_path: Path,
    signed: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier, token, _ = signed
    owner = service(tmp_path)
    app = HubApplication(owner, "admin" * 16, browser_access=verifier)
    with owner.operations.transaction() as db:
        for number in range(155):
            db.execute(
                "INSERT INTO uploads(id,device,content_id,manifest_sha,intent,status) "
                "VALUES(?,?,?,?,?,?)",
                (
                    f"{number:032x}",
                    "one" if number % 2 else "two",
                    f"{number:064x}",
                    "b" * 64,
                    "private-intent-not-valid-json",
                    "verified",
                ),
            )
    owner.console_index.collection(
        f"{1:032x}",
        100,
        {"schema": "owner-summary", "counts": {"canonical": 20, "real_failures": 1}},
    )
    monkeypatch.setattr(owner.store, "get_manifest", lambda *a: pytest.fail("GET read store"))
    monkeypatch.setattr(owner.store, "manifest_ids", lambda: pytest.fail("GET scanned store"))
    status, page = call(app, "/app/api/collections", token=token(), query="limit=100")
    assert status == "200 OK" and len(page["items"]) == 100 and page["total"] == 155
    assert page["next_offset"] == 100
    page2 = call(app, "/app/api/collections", token=token(), query="offset=100&limit=100")[1]
    assert len(page2["items"]) == 55 and page2["next_offset"] is None
    own = call(app, "/v1/console/collections", bearer="one" * 16, query="limit=100")[1]
    assert own["total"] == 77 and {r["device_id"] for r in own["items"]} == {"one"}
    denied = call(
        app, "/app/api/collections/" + f"{0:032x}", token=token(email="collector@example.org")
    )
    assert denied[0] == "404 Not Found"
    details = call(app, "/v1/console/collections/" + f"{1:032x}", bearer="one" * 16)[1]["item"]
    assert details["summary"]["counts"]["real_failures"] == 1
    assert details["status"] == "verified" and details["summary_status"] == "available"
    assert details["timeline"] == [] and details["created_at"] is None
    assert "private-intent" not in json.dumps(own)
    assert (
        call(app, "/v1/console/collections", bearer="one" * 16, query="limit=101")[0]
        == "400 Bad Request"
    )


def test_safe_artifact_metadata_roles_and_unknown_lineage(tmp_path: Path, signed: Any) -> None:
    verifier, token, _ = signed
    owner = service(tmp_path)
    source = Manifest("evidence", owner.producer)
    dataset = Manifest(
        "dataset",
        owner.producer,
        parents=(Parent("source", source.artifact_id),),
        parameters=FrozenObject.of({"records": 20, "sealed_test": "NEVER_EXPOSE"}),
    )
    model = Manifest(
        "model",
        owner.producer,
        parents=(Parent("dataset", dataset.artifact_id),),
        parameters=FrozenObject.of({"metrics": {"sealed_test": "NEVER_EXPOSE"}}),
    )
    for manifest in (source, dataset, model):
        owner.store.publish(manifest)
        owner.console_index.artifact(manifest)
    app = HubApplication(owner, "admin" * 16, browser_access=verifier)
    assert (
        call(app, "/v1/console/datasets", bearer="one" * 16)[1]["availability"] == "not_authorized"
    )
    assert (
        call(app, "/v1/artifacts/" + dataset.artifact_id, bearer="one" * 16)[0]
        == "401 Unauthorized"
    )
    assert (
        call(app, "/app/api/models", token=token(email="collector@example.org"))[1]["items"][0][
            "parents"
        ]
        == []
    )
    models = call(app, "/app/api/models", token=token())[1]
    assert models["items"][0]["parents"] == [
        {"role": "dataset", "artifact_id": dataset.artifact_id}
    ]
    datasets = call(app, "/app/api/datasets", token=token())[1]
    detail = call(app, "/app/api/datasets/" + dataset.artifact_id, token=token())[1]
    assert detail["item"]["artifact_id"] == dataset.artifact_id
    assert call(app, "/app/api/models/" + "f" * 64, token=token())[0] == "404 Not Found"
    assert datasets["items"][0]["lineage_partial"] is True
    assert "NEVER_EXPOSE" not in json.dumps([models, datasets])
    assert (
        call(app, "/app/api/artifacts/" + dataset.artifact_id, token=token())[0] == "404 Not Found"
    )


def test_private_config_absence_partial_issuer_and_permissions(tmp_path: Path) -> None:
    assert configured_access({}) is None
    with pytest.raises(BoundaryError, match="incomplete"):
        configured_access({"STPD_ACCESS_ISSUER": ISSUER})
    for issuer in (
        "http://team.cloudflareaccess.com",
        "https://evil.invalid",
        "https://a.cloudflareaccess.com@evil.invalid",
        ISSUER + "/",
    ):
        with pytest.raises(BoundaryError, match="invalid_access_issuer"):
            AccessVerifier(issuer, AUDIENCE, [])
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(
        json.dumps(
            {
                "schema": "stpd/console-access-v1",
                "principals": [
                    {"email": "owner@example.org", "role": "operator", "devices": ["one"]}
                ],
            }
        )
    )
    env = {
        "STPD_ACCESS_ISSUER": ISSUER,
        "STPD_ACCESS_AUDIENCE": AUDIENCE,
        "STPD_ACCESS_ALLOWLIST": str(allowlist),
    }
    allowlist.chmod(0o600)
    assert configured_access(env) is not None
    if __import__("os").name != "nt":
        allowlist.chmod(0o644)
        with pytest.raises(BoundaryError, match="private_bounded"):
            configured_access(env)
    for query in (
        "limit=0",
        "limit=101",
        "offset=-1",
        "limit=1&limit=2",
        "token=secret",
        "limit=",
        "status=invalid",
        "offset=1000001",
    ):
        with pytest.raises(BoundaryError, match="invalid_pagination"):
            pagination(query)


def test_projection_index_reads_dont_change_operations_or_journal(tmp_path: Path) -> None:
    owner = service(tmp_path)
    row = owner.operations.create_upload("one", "a" * 64, "b" * 64, {})
    before = owner.operations.upload(row["id"])
    with owner.operations.transaction() as db:
        events = list(db.execute("SELECT * FROM events"))
    index = ConsoleIndex(owner.operations)
    principal = ConsolePrincipal("collector", ("one",))
    for _ in range(3):
        assert index.collections(principal, limit=25, offset=0)["total"] == 1
    assert owner.operations.upload(row["id"]) == before
    with owner.operations.transaction() as db:
        assert [tuple(r) for r in db.execute("SELECT * FROM events")] == [tuple(r) for r in events]


def test_bundle_summary_refresh_preserves_receipt_and_uses_verified_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gzip
    import hashlib
    import tarfile

    import sts2_platform_evidence
    from platform_bundle3_fixture import bundle3
    from sts2_platform_evidence import DirectoryTransferManifest, verify_human_session_bundle

    owner = service(tmp_path)
    bundle = bundle3(tmp_path / "bundle-fixture")
    verified = verify_human_session_bundle(bundle).require_value()
    transfer = DirectoryTransferManifest.from_directory(
        bundle, content_id=verified.bundle_content_id, artifact_type="human-session-bundle"
    )
    source = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=source, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        for entry in transfer.files:
            archive.add(bundle / entry.path, arcname=entry.path)
    raw = source.getvalue()
    called = []
    summary = {
        "schema": "test/owner-summary",
        "content_id": verified.bundle_content_id,
        "counts": {"canonical": 6, "real_failures": 0},
    }

    def summarize(value: Any) -> dict:
        assert value.bundle_content_id == verified.bundle_content_id
        called.append(value.bundle_content_id)
        return summary

    # The new owner public API is integrated via an exact Platform pin by the lead.
    # This regression checks correlation/publication, not Platform summary accounting.
    monkeypatch.setattr(
        sts2_platform_evidence, "summarize_verified_human_bundle", summarize, raising=False
    )
    intent = {
        "schema": "stpd/upload-intent-v1",
        "transfer_manifest": transfer.to_dict(),
        "archive_sha256": hashlib.sha256(raw).hexdigest(),
        "archive_bytes": len(raw),
    }
    upload_id = owner.intent("one", intent)["upload_id"]
    assert isinstance(owner.staging, LocalStaging)
    owner.staging.write(upload_id, io.BytesIO(raw), len(raw))
    owner.operations.request_verification(upload_id)
    assert owner.verify_pending() == 1 and len(called) == 1
    before = owner.operations.upload(upload_id)
    original_manifests = owner.store.manifest_ids()
    principal = ConsolePrincipal("operator", ("one",))
    row = owner.console_index.collections(principal, limit=1, offset=0)["items"][0]
    assert row["summary"] == summary and row["status"] == "verified"
    assert owner.intent("one", intent)["upload_id"] == upload_id
    assert (
        owner.console_index.collections(principal, limit=1, offset=0)["items"][0]["summary"]
        == summary
    )
    owner.console_index.collection(upload_id, len(raw), None, status="unavailable")
    assert owner.refresh_console(upload_id=upload_id)["collections_indexed"] == 1
    assert len(called) == 2
    assert owner.operations.upload(upload_id) == before
    assert owner.store.manifest_ids() == original_manifests


def test_dataset_usage_links_exact_received_identity_without_raw_closure(tmp_path: Path) -> None:
    owner = service(tmp_path)
    received = Manifest("evidence", owner.producer)
    source = Manifest(
        "evidence", owner.producer, parents=(Parent("received", received.artifact_id),)
    )
    dataset = Manifest("dataset", owner.producer, parents=(Parent("source", source.artifact_id),))
    for manifest in (received, source, dataset):
        owner.store.publish(manifest)
    assert owner.console_index.artifact_closure(owner.store, (dataset.artifact_id,)) == 3
    upload = owner.operations.create_upload("one", "a" * 64, "b" * 64, {})
    owner.operations.finish_upload(
        upload["id"],
        {
            "content_id": "a" * 64,
            "manifest_sha256": "b" * 64,
            "status": "verified",
            "evidence_id": received.artifact_id,
        },
    )
    result = owner.console_index.collections(
        ConsolePrincipal("reviewer", ("one",)), limit=1, offset=0, upload_id=upload["id"]
    )["item"]
    assert result["research"]["dataset_ids"] == [dataset.artifact_id]
    assert result["research"]["status"] == "dataset_references_present"
    collector = owner.console_index.collections(
        ConsolePrincipal("collector", ("one",)), limit=1, offset=0, upload_id=upload["id"]
    )["item"]
    assert "dataset_ids" not in collector["research"]
    assert source.artifact_id not in json.dumps(result)


def test_job_list_is_bounded_and_redacts_worker_private_result(tmp_path: Path) -> None:
    owner = service(tmp_path)
    with owner.operations.transaction() as db:
        for index in range(105):
            db.execute(
                "INSERT INTO jobs(id,request_key,kind,input_id,max_seconds,reserved_units,"
                "status,result) VALUES(?,?,?,?,?,?,?,?)",
                (
                    f"{index:032x}",
                    str(index),
                    "training",
                    "a" * 64,
                    5,
                    1,
                    "completed",
                    json.dumps(
                        {
                            "output_id": "b" * 64,
                            "secret": "NEVER_EXPOSE",
                            "metrics": {"test": 1},
                            "path": "/private/path",
                        }
                    ),
                ),
            )
    result = owner.console_index.jobs(limit=100, offset=0)
    assert result["total"] == 105 and result["next_offset"] == 100
    assert len(owner.console_index.jobs(limit=100, offset=100)["items"]) == 5
    encoded = json.dumps(result)
    assert (
        "NEVER_EXPOSE" not in encoded and "/private/path" not in encoded and '"test"' not in encoded
    )


def test_public_landing_has_no_private_scope_or_identity(tmp_path: Path) -> None:
    owner = service(tmp_path)
    app = HubApplication(owner, "admin" * 16)
    status, html = call(app, "/")
    assert status == "200 OK" and b"/app/" in html
    assert owner.producer.source_revision.encode() not in html
    assert b"device_ids" not in html and b"verified" not in html


def test_jwks_outage_is_bounded_and_never_reuses_expired_cache(signed: Any) -> None:
    verifier, token, _ = signed
    assert verifier.authenticate(token()).role == "operator"
    calls = []

    def failed() -> None:
        calls.append(1)
        raise OSError("private-network-detail-not-exposed")

    verifier.fetch_keys = failed
    verifier._refresh_at = 0
    for _ in range(5):
        with pytest.raises(BoundaryError, match="unauthorized") as error:
            verifier.authenticate(token())
        assert "private-network" not in str(error.value)
    assert len(calls) == 1


def test_verification_request_time_is_observed_once_never_backfilled(tmp_path: Path) -> None:
    owner = service(tmp_path)
    row = owner.operations.create_upload("one", "a" * 64, "b" * 64, {})
    owner.operations.request_verification(row["id"])
    owner.operations.request_verification(row["id"])
    result = owner.console_index.collections(
        ConsolePrincipal("collector", ("one",)), limit=1, offset=0, upload_id=row["id"]
    )["item"]
    operations = [event["operation"] for event in result["timeline"]]
    assert operations == ["upload_created", "upload_verification_requested"]
    assert result["status"] == "verification_pending" and result["verified_at"] is None


def test_sealed_evaluations_and_gold_do_not_enter_discovery(tmp_path: Path) -> None:
    owner = service(tmp_path)
    sealed = Manifest(
        "offline_evaluation",
        owner.producer,
        parameters=FrozenObject.of({"partition": "test", "records": 50}),
    )
    gold = Manifest("gold_labels", owner.producer)
    dev = Manifest(
        "offline_evaluation",
        owner.producer,
        parameters=FrozenObject.of({"partition": "dev", "records": 20}),
    )
    for manifest in (sealed, gold, dev):
        owner.console_index.artifact(manifest)
    result = owner.console_index.artifacts(
        ConsolePrincipal("operator", ("one",)), "models", limit=25, offset=0
    )
    assert [row["artifact_id"] for row in result["items"]] == [dev.artifact_id]
    assert sealed.artifact_id not in json.dumps(result) and gold.artifact_id not in json.dumps(
        result
    )
