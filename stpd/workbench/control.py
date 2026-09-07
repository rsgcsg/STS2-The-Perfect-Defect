"""Local control plane adapters; durable research identities never depend on a provider."""

from __future__ import annotations

import hashlib
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

from ..artifact_contracts import Producer
from ..json_boundary import BoundaryError
from ..storage.blobs import StoreError
from ..storage.local import LocalBlobStore
from ..storage.s3 import S3BlobStore, S3Config
from ..storage.store import ManifestArtifactStore

REPOSITORY = "rsgcsg/STS2-The-Perfect-Defect"


def source_identity(root: Path, *, require_clean: bool = True) -> Producer:
    if root.resolve() != Path(__file__).resolve().parents[2]:
        raise BoundaryError("source", "executing_package_checkout_mismatch")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=root)
    if require_clean and dirty:
        raise BoundaryError("source", "clean_checkout_required")
    lock = (root / "uv.lock").read_bytes()
    committed = subprocess.check_output(["git", "show", "HEAD:uv.lock"], cwd=root)
    if lock != committed:
        raise BoundaryError("source", "working_lock_mismatch")
    return Producer(REPOSITORY, head, hashlib.sha256(lock).hexdigest())


def open_store(location: str) -> ManifestArtifactStore:
    """'s3' selects environment configuration; every other value is a local directory."""
    if location == "s3":
        bucket = os.environ.get("STPD_S3_BUCKET")
        if not bucket:
            raise BoundaryError("configuration", "missing_s3_bucket")
        config = S3Config(
            bucket=bucket,
            endpoint=os.environ.get("STPD_S3_ENDPOINT") or None,
            prefix=os.environ.get("STPD_S3_PREFIX", "stpd"),
            region=os.environ.get("STPD_S3_REGION", "us-east-1"),
        )
        return ManifestArtifactStore(S3BlobStore(config))
    return ManifestArtifactStore(LocalBlobStore(Path(location)))


def doctor(store: ManifestArtifactStore, *, smoke: bool = False) -> dict[str, Any]:
    """Read and verify all indexed artifacts; optional isolated immutable write probe."""
    identities = store.manifest_ids()
    for identity in identities:
        manifest = store.get_manifest(identity)
        for parent in manifest.parents:
            store.get_manifest(parent.artifact_id)
        for payload in manifest.payloads:
            for _ in store.read_payload(payload):
                pass
    if smoke:
        key = f"doctor/{uuid.uuid4().hex}"
        if not store.blobs.put_if_absent(key, b"stpd-doctor-v1"):
            raise StoreError("doctor_initial_write_collision")
        if store.blobs.put_if_absent(key, b"stpd-doctor-v1"):
            raise StoreError("doctor_idempotency_failed")
        try:
            store.blobs.put_if_absent(key, b"different")
        except StoreError as error:
            if error.code != "immutable_key_collision":
                raise
        else:
            raise StoreError("doctor_conditional_write_failed")
        if store.blobs.get(key) != b"stpd-doctor-v1":
            raise StoreError("doctor_readback_failed")
    return {
        "schema": "stpd/store-doctor-v1",
        "verified_manifests": len(identities),
        "integrity": "PASS",
        "conditional_smoke": "PASS" if smoke else "NOT_RUN",
        "non_claims": ["provider-wide qualification", "scientific validity"],
    }


def launch_packet(store: ManifestArtifactStore, run_id: str, runtime: Producer) -> dict[str, Any]:
    from ..workers.contracts import load_training_input

    run = store.get_manifest(run_id)
    if run.kind != "run" or run.producer != runtime:
        raise BoundaryError("launch", "run_source_mismatch")
    load_training_input(store, run.parent("training_input"), runtime)
    return {
        "schema": "stpd/manual-linux-launch-v1",
        "run_id": run_id,
        "producer": runtime.to_dict(),
        "provider": "generic-disposable-linux",
        "commands": [
            ["git", "clone", "https://github.com/" + REPOSITORY + ".git", "stpd"],
            ["git", "-C", "stpd", "checkout", "--detach", runtime.source_revision],
            ["uv", "sync", "--locked", "--all-extras"],
            [
                "uv",
                "run",
                "--locked",
                "python",
                "-m",
                "stpd.workbench",
                "worker",
                "--store",
                "s3",
                "--run",
                run_id,
            ],
        ],
        "working_directory_after_checkout": "stpd",
        "prerequisites": ["Git", "uv", "Python 3.11", "CUDA matching locked torch if configured"],
        "storage_environment_names": [
            "STPD_S3_BUCKET",
            "STPD_S3_ENDPOINT",
            "STPD_S3_PREFIX",
            "STPD_S3_REGION",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
        ],
        "recovery": "Repeat the exact worker command with --resume <durable-checkpoint-id>.",
        "preflight": "Push the exact Run lineage to s3 before launch; supply credentials via env.",
        "non_claims": ["GPU account provisioned", "provider qualified", "scientific admission"],
    }
