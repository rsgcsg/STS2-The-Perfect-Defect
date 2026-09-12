"""Developer Hub CLI; real cloud resources require explicit configured credentials."""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..json_boundary import BoundaryError, decode_json
from ..workbench.control import open_store, source_identity
from .application import HubApplication
from .database import Operations
from .uploads import LocalStaging, S3Staging, Staging, UploadService


def configured_service(args: Any) -> UploadService:
    producer = source_identity(args.root)
    operations = Operations(args.state / "operations.sqlite")
    staging: Staging
    if args.staging == "s3":
        from ..storage.s3 import S3Config, client_for

        bucket = os.environ.get("STPD_INGRESS_BUCKET")
        if not bucket:
            raise BoundaryError("hub", "missing_ingress_bucket")
        config = S3Config(
            bucket,
            os.environ.get("STPD_S3_ENDPOINT"),
            region=os.environ.get("STPD_S3_REGION", "auto"),
        )
        staging = S3Staging(client_for(config), bucket)
    else:
        parsed = urlsplit(args.public_url)
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise BoundaryError("hub", "local_staging_loopback_only")
        staging = LocalStaging(args.state / "incoming", args.public_url)
    return UploadService(operations, staging, open_store(args.store), producer)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "serve",
            "verify",
            "register",
            "revoke",
            "status",
            "pause",
            "unpause",
            "backup",
            "reconcile",
            "dataset",
            "feature-job",
            "prepare-run",
            "enqueue",
            "retry-upload",
        ],
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--state", type=Path, default=Path(".local/hub"))
    parser.add_argument("--store", default=".local/hub-artifacts")
    parser.add_argument("--staging", choices=["local", "s3"], default="local")
    parser.add_argument("--public-url", default="http://127.0.0.1:8765")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--device")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--job")
    parser.add_argument("--upload")
    parser.add_argument("--received", action="append", default=[])
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--input-id")
    parser.add_argument("--feature-id")
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--kind", choices=["feature", "training"])
    parser.add_argument("--request-key")
    parser.add_argument("--max-seconds", type=int, default=300)
    parser.add_argument("--reserved-units", type=int, default=0)
    parser.add_argument("--resume")
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--modal-target", type=Path, help="exact deployed ModalTarget JSON")
    parser.add_argument("--isolated", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--evidence", help="operator-reviewed provider stop evidence reference")
    parser.add_argument(
        "--budget-units",
        type=int,
        default=0,
        help="explicit campaign reservation cap, zero disables new jobs",
    )
    args = parser.parse_args()
    try:
        if args.isolated:
            from .verification_worker import constrain_worker

            constrain_worker()
        service = configured_service(args)
        ops = service.operations
        if args.command == "register":
            if not args.device or not os.environ.get("STPD_DEVICE_TOKEN"):
                raise BoundaryError("hub", "device_and_env_token_required")
            ops.register(args.device, os.environ["STPD_DEVICE_TOKEN"])
            print(json.dumps({"registered": args.device}))
        elif args.command == "revoke":
            if not args.device:
                raise BoundaryError("hub", "device_required")
            ops.revoke(args.device)
            print(json.dumps({"revoked": args.device}))
        elif args.command in {"pause", "unpause"}:
            if args.command == "unpause" and any(
                row["status"] in {"running", "uncertain", "submission_unknown", "cancelling"}
                for row in ops.jobs()
            ):
                raise BoundaryError("hub", "reconcile_external_jobs_before_unpause")
            ops.pause(args.command == "pause")
            print(json.dumps({"paused": ops.paused()}))
        elif args.command == "backup":
            if args.backup is None:
                raise BoundaryError("hub", "backup_destination_required")
            ops.backup(args.backup)
            print(json.dumps({"backup": "completed", "restore_mode": "paused"}))
        elif args.command == "reconcile":
            if not args.job or not args.evidence:
                raise BoundaryError("hub", "job_and_stop_evidence_required")
            ops.reconcile_stopped(args.job, args.evidence)
            print(json.dumps({"reconciled": args.job}))
        elif args.command == "verify":
            print(json.dumps({"processed": service.verify_pending(args.upload)}))
        elif args.command == "retry-upload":
            if not args.upload:
                raise BoundaryError("hub", "upload_required")
            ops.retry_upload(args.upload)
            print(json.dumps({"retry_authorized": args.upload}))
        elif args.command == "dataset":
            from .pipeline import build_dataset

            print(
                json.dumps(
                    build_dataset(
                        service.store, tuple(args.received), service.producer, seed=args.seed
                    )
                )
            )
        elif args.command == "feature-job":
            from ..cloud_jobs.contracts import FeatureJobSpec
            from .pipeline import prepare_features

            if not args.input_id or not args.spec:
                raise BoundaryError("hub", "dataset_and_spec_required")
            spec = FeatureJobSpec.decode(decode_json(args.spec.read_bytes()))
            print(
                json.dumps(prepare_features(service.store, args.input_id, spec, service.producer))
            )
        elif args.command == "prepare-run":
            from ..cloud_jobs.execution import prepare_feature_run

            if not args.input_id or not args.feature_id:
                raise BoundaryError("hub", "feature_job_and_output_required")
            print(
                json.dumps(
                    asdict(
                        prepare_feature_run(
                            service.store, args.input_id, args.feature_id, service.producer
                        )
                    )
                )
            )
        elif args.command == "enqueue":
            if not args.kind or not args.input_id or not args.request_key:
                raise BoundaryError("hub", "job_fields_required")
            job = ops.enqueue(
                args.kind,
                args.input_id,
                args.request_key,
                max_seconds=args.max_seconds,
                reserved_units=args.reserved_units,
                budget_limit=args.budget_units,
                options={"resume": args.resume, "stop_after": args.stop_after},
            )
            print(json.dumps({"job_id": job}))
        elif args.command == "status":
            print(
                json.dumps(
                    {
                        "paused": ops.paused(),
                        "uploads": sum(ops.upload_counts().values()),
                        "jobs": len(ops.jobs()),
                    }
                )
            )
        else:
            from waitress import serve  # type: ignore[import-untyped]

            from .verification_worker import run_verifier

            secret = os.environ.get("STPD_HUB_ADMIN_TOKEN", "")
            app = HubApplication(service, secret, budget_limit=args.budget_units)
            if args.host not in {"localhost", "127.0.0.1", "::1"}:
                raise BoundaryError("hub", "bind_loopback_use_tls_reverse_proxy")
            shutdown = threading.Event()
            scheduler = None
            scheduler_thread = None
            if args.modal_target is not None:
                from ..cloud_jobs.modal import ModalProvider, ModalTarget
                from .scheduler import Scheduler

                target = ModalTarget.decode(decode_json(args.modal_target.read_bytes()))
                if target.producer != service.producer:
                    raise BoundaryError("hub", "modal_target_source_mismatch")
                scheduler = Scheduler(
                    ops, service.store, ModalProvider(target), budget_limit=args.budget_units
                )

                def schedule() -> None:
                    assert scheduler is not None
                    while not shutdown.is_set():
                        try:
                            result = scheduler.tick(time.time())
                            if result["state"] != "idle":
                                print(json.dumps(result), flush=True)
                        except Exception as error:
                            code = error.code if isinstance(error, BoundaryError) else "tick_failed"
                            print(json.dumps({"stage": "scheduler", "error": code}), flush=True)
                        shutdown.wait(5)

                scheduler_thread = threading.Thread(target=schedule, daemon=True)
                scheduler_thread.start()

            def verifier() -> None:
                while not shutdown.is_set():
                    pending = ops.pending_upload(time.time())
                    if pending is None:
                        shutdown.wait(5)
                        continue
                    arguments = [
                        "--root",
                        str(args.root.resolve()),
                        "--state",
                        str(args.state.resolve()),
                        "--store",
                        args.store,
                        "--staging",
                        args.staging,
                        "--public-url",
                        args.public_url,
                        "--upload",
                        pending["id"],
                    ]
                    if not run_verifier(arguments, shutdown=shutdown) and not shutdown.is_set():
                        ops.verification_failure(
                            pending["id"], "verifier_resource_or_process_limit", now=time.time()
                        )
                        print(
                            json.dumps({"stage": "verification", "state": "retry_pending"}),
                            flush=True,
                        )
                    shutdown.wait(5)

            thread = threading.Thread(target=verifier, daemon=True)
            thread.start()

            def stop_signal(signum: int, frame: Any) -> None:
                raise KeyboardInterrupt

            signal.signal(signal.SIGTERM, stop_signal)
            try:
                print(
                    json.dumps(
                        {
                            "service": "stpd-hub",
                            "source": service.producer.source_revision,
                            "port": args.port,
                        }
                    ),
                    flush=True,
                )
                serve(
                    app,
                    host=args.host,
                    port=args.port,
                    threads=4,
                    connection_limit=32,
                    channel_timeout=30,
                    max_request_body_size=512 * 1024 * 1024,
                    expose_tracebacks=False,
                )
            finally:
                shutdown.set()
                thread.join(timeout=5)
                if scheduler_thread is not None:
                    scheduler_thread.join(timeout=5)
                if scheduler is not None:
                    scheduler.close()
        return 0
    except KeyboardInterrupt:
        return 130
    except (BoundaryError, ValueError, OSError) as error:
        print(
            json.dumps(
                {
                    "error": error.code
                    if isinstance(error, BoundaryError)
                    else "hub_operation_failed"
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
