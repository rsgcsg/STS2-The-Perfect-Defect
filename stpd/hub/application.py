"""Authenticated WSGI boundary; independent worker verifies pending uploads."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from collections.abc import Callable, Iterable
from typing import Any

from ..json_boundary import BoundaryError, decode_json, json_bytes
from .database import token_hash
from .uploads import LocalStaging, UploadService


class HubApplication:
    def __init__(self, service: UploadService, admin_token: str, *, budget_limit: int = 0) -> None:
        if len(admin_token) < 32:
            raise BoundaryError("hub", "admin_token_too_short")
        self.service = service
        self.admin_hash = token_hash(admin_token)
        self.capability_key = hashlib.sha256(("upload-capability:" + admin_token).encode()).digest()
        self.budget_limit = budget_limit

    def capability(self, upload_id: str, deadline: int) -> str:
        signature = hmac.new(
            self.capability_key, f"{upload_id}:{deadline}".encode(), hashlib.sha256
        ).hexdigest()
        return f"{deadline}.{signature}"

    def validate_capability(self, upload_id: str, value: str) -> None:
        try:
            deadline = int(value.split(".")[0])
        except ValueError:
            raise BoundaryError("hub", "unauthorized") from None
        if deadline < time.time() or not secrets.compare_digest(
            value, self.capability(upload_id, deadline)
        ):
            raise BoundaryError("hub", "unauthorized")

    def __call__(
        self, environ: dict[str, Any], start_response: Callable[..., Any]
    ) -> Iterable[bytes]:
        try:
            status, kind, body = self.route(environ)
        except BoundaryError as error:
            status = "401 Unauthorized" if error.code == "unauthorized" else "409 Conflict"
            kind, body = "application/json", json_bytes({"error": error.code})
        except (ValueError, KeyError, TypeError):
            status, kind, body = (
                "400 Bad Request",
                "application/json",
                b'{"error":"invalid_request"}',
            )
        except Exception:
            status, kind, body = (
                "503 Service Unavailable",
                "application/json",
                b'{"error":"service_operation_failed"}',
            )
        headers = [
            ("Content-Type", kind),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("Content-Security-Policy", "default-src 'none'"),
        ]
        if isinstance(body, bytes):
            headers.append(("Content-Length", str(len(body))))
            start_response(status, headers)
            return [body]
        start_response(status, headers)
        return body

    @staticmethod
    def body(environ: dict[str, Any]) -> Any:
        length = int(environ.get("CONTENT_LENGTH") or "0")
        if not 0 < length <= 8 * 1024 * 1024:
            raise BoundaryError("hub", "request_size_limit")
        raw = environ["wsgi.input"].read(length)
        if len(raw) != length:
            raise BoundaryError("hub", "truncated_request")
        return decode_json(raw)

    @staticmethod
    def response(value: Any, status: str = "200 OK") -> tuple[str, str, bytes]:
        return status, "application/json", json_bytes(value)

    @staticmethod
    def upload_status(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "upload_id": row["id"],
            "content_id": row["content_id"],
            "status": row["status"],
            "receipt": json.loads(row["receipt"]) if row["receipt"] else None,
        }

    def route(self, env: dict[str, Any]) -> tuple[str, str, bytes | Iterable[bytes]]:
        method, path = env["REQUEST_METHOD"], env.get("PATH_INFO", "")
        ops = self.service.operations
        if method == "GET" and path == "/health":
            return self.response({"service": "stpd-hub", "schema": "stpd/hub-health-v1"})
        upload = re.fullmatch(r"/v1/uploads/([a-f0-9]{32})(?:/(body|complete))?", path)
        if method == "PUT" and upload and upload[2] == "body":
            self.validate_capability(upload[1], env.get("HTTP_X_UPLOAD_CAPABILITY", ""))
            row = ops.upload(upload[1])
            with ops.transaction() as db:
                active = db.execute(
                    "SELECT active FROM devices WHERE id=?", (row["device"],)
                ).fetchone()
                if active is None or not active[0]:
                    raise BoundaryError("hub", "unauthorized")
            if not isinstance(self.service.staging, LocalStaging):
                raise BoundaryError("hub", "direct_store_upload_required")
            if row["status"] != "awaiting_upload":
                raise BoundaryError("hub", "upload_already_sealed")
            size = json.loads(row["intent"])["archive_bytes"]
            if int(env.get("CONTENT_LENGTH") or "0") != size:
                raise BoundaryError("hub", "archive_size_mismatch")
            self.service.staging.write(upload[1], env["wsgi.input"], size)
            return self.response({"uploaded": True})
        authorization = env.get("HTTP_AUTHORIZATION", "")
        if not authorization.startswith("Bearer "):
            raise BoundaryError("hub", "unauthorized")
        token = authorization[7:]
        admin = secrets.compare_digest(self.admin_hash, token_hash(token))
        device = None if admin else ops.authenticate(token)
        if method == "GET" and path == "/v1/status":
            counts: dict[str, int] = {}
            for item in ops.uploads(device):
                counts[item["status"]] = counts.get(item["status"], 0) + 1
            return self.response(
                {
                    "schema": "stpd/hub-status-v1",
                    "version": 1,
                    "counts": counts,
                    "paused": ops.paused(),
                }
            )
        if method == "GET" and path in {"/v1/uploads", "/v1/incidents"}:
            items = [self.upload_status(row) for row in ops.uploads(device)]
            if path.endswith("incidents"):
                items = [row for row in items if row["status"] == "quarantined"]
            return self.response({"items": items})
        if method == "POST" and path == "/v1/uploads":
            if device is None:
                raise BoundaryError("hub", "collector_identity_required")
            result = self.service.intent(device, self.body(env))
            if isinstance(self.service.staging, LocalStaging):
                result["upload_headers"]["X-Upload-Capability"] = self.capability(
                    result["upload_id"], int(time.time()) + 900
                )
            return self.response(result, "201 Created")
        if upload:
            row = ops.upload(upload[1], device)
            if method == "POST" and upload[2] == "complete":
                ops.request_verification(row["id"])
                row = ops.upload(row["id"], device)
            elif method != "GET" or upload[2] is not None:
                return self.response({"error": "not_found"}, "404 Not Found")
            return self.response(self.upload_status(row))
        if not admin:
            raise BoundaryError("hub", "unauthorized")
        if method == "GET" and path == "/v1/jobs":
            return self.response(
                {
                    "items": [
                        {k: v for k, v in row.items() if k != "lease_hash"} for row in ops.jobs()
                    ]
                }
            )
        if method == "POST" and path == "/v1/jobs":
            body = self.body(env)
            job_id = ops.enqueue(
                body["kind"],
                body["input_id"],
                body["request_key"],
                max_seconds=body["max_seconds"],
                reserved_units=body["reserved_units"],
                budget_limit=self.budget_limit,
            )
            return self.response({"job_id": job_id}, "201 Created")
        if method == "POST" and path == "/v1/pause":
            value = self.body(env)["paused"]
            if type(value) is not bool:
                raise BoundaryError("hub", "invalid_pause")
            ops.pause(value)
            return self.response({"paused": value})
        match = re.fullmatch(r"/v1/jobs/([a-f0-9]{32})/cancel", path)
        if match and method == "POST":
            ops.cancel(match[1])
            return self.response({"cancel_requested": True})
        match = re.fullmatch(r"/v1/artifacts/([a-f0-9]{64})(?:/payloads/([a-z0-9_]+))?", path)
        if match and method == "GET":
            manifest = self.service.store.get_manifest(match[1])
            if match[2] is None:
                return self.response(decode_json(manifest.to_bytes()))
            return (
                "200 OK",
                "application/octet-stream",
                self.service.store.read_payload(manifest.payload(match[2])),
            )
        return self.response({"error": "not_found"}, "404 Not Found")
