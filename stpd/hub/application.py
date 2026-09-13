"""Authenticated WSGI boundary; independent worker verifies pending uploads."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from ..json_boundary import BoundaryError, decode_json, json_bytes
from .access import RESULT_KINDS
from .console_auth import AccessVerifier, ConsolePrincipal
from .database import token_hash
from .uploads import LocalStaging, UploadService


class HubApplication:
    def __init__(
        self,
        service: UploadService,
        admin_token: str,
        *,
        budget_limit: int = 0,
        browser_access: AccessVerifier | None = None,
        backup_status: Path | None = None,
    ) -> None:
        if len(admin_token) < 32:
            raise BoundaryError("hub", "admin_token_too_short")
        self.service = service
        self.admin_hash = token_hash(admin_token)
        self.capability_key = hashlib.sha256(("upload-capability:" + admin_token).encode()).digest()
        self.budget_limit = budget_limit
        self.browser_access = browser_access
        from .console_routes import ConsoleRoutes

        self.console = ConsoleRoutes(
            service,
            budget_limit,
            backup_status=backup_status,
            browser_enabled=browser_access is not None,
        )

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
            status = {
                "unauthorized": "401 Unauthorized",
                "browser_access_not_configured": "503 Service Unavailable",
                "collection_not_found": "404 Not Found",
                "resource_not_found": "404 Not Found",
                "invalid_pagination": "400 Bad Request",
                "unexpected_query": "400 Bad Request",
                "status_filter_requires_collections": "400 Bad Request",
            }.get(error.code, "409 Conflict")
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
            (
                "Content-Security-Policy",
                "default-src 'none'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'",
            ),
            ("Referrer-Policy", "no-referrer"),
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
        if not 0 < length <= 32 * 1024 * 1024:
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
        # Persisted owner error codes are useful; raw exception text/URLs are not public status.
        error = row.get("last_error")
        if error is not None and (
            not isinstance(error, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,95}", error) is None
        ):
            error = "operational_error_redacted"
        return {
            "upload_id": row["id"],
            "content_id": row["content_id"],
            "status": row["status"],
            "receipt": json.loads(row["receipt"]) if row["receipt"] else None,
            "verify_attempts": row["verify_attempts"],
            "retry_at": row["retry_at"] if row["status"] == "verification_pending" else None,
            "last_error": error,
        }

    def route(self, env: dict[str, Any]) -> tuple[str, str, bytes | Iterable[bytes]]:
        method, path = env["REQUEST_METHOD"], env.get("PATH_INFO", "")
        ops = self.service.operations
        if method == "GET" and path == "/":
            return (
                "200 OK",
                "text/html; charset=utf-8",
                (
                    "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
                    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                    "<title>SpireAgent 项目控制台</title><main>"
                    "<h1>SpireAgent 项目控制台</h1>"
                    "<p><a href='/app/'>登录查看云端数据</a></p>"
                    "<p>本机设备连接与网页登录分开；网页登录或退出不影响后台上传。</p>"
                    "<p>云端只显示已收到的数据。本机待上传队列请在本机控制台查看。</p>"
                    "</main></html>"
                ).encode(),
            )
        if method == "GET" and path == "/health":
            return self.response(
                {
                    "service": "stpd-hub",
                    "schema": "stpd/hub-health-v1",
                    "producer": self.service.producer.to_dict(),
                }
            )
        if path == "/app" or path.startswith("/app/"):
            if self.browser_access is None:
                raise BoundaryError("console", "browser_access_not_configured")
            principal = self.browser_access.authenticate(
                env.get("HTTP_CF_ACCESS_JWT_ASSERTION", "")
            )
            if method != "GET":
                return self.response({"error": "console_read_only"}, "405 Method Not Allowed")
            if path.startswith("/app/api/"):
                return self.response(
                    self.console.read(
                        path[len("/app/api/") :], env.get("QUERY_STRING", ""), principal
                    )
                )
            from ..console.page import asset, render_shell

            if path in {"/app", "/app/"}:
                return (
                    "200 OK",
                    "text/html; charset=utf-8",
                    render_shell(mode="cloud", api_base="/app/api").encode(),
                )
            if path.startswith("/app/assets/"):
                found = asset(path.removeprefix("/app/assets/"))
                if found is not None:
                    return "200 OK", found[0], found[1]
            return self.response({"error": "not_found"}, "404 Not Found")
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
        if path.startswith("/v1/console/"):
            if method != "GET":
                return self.response({"error": "console_read_only"}, "405 Method Not Allowed")
            if admin:
                with ops.transaction() as db:
                    devices = tuple(
                        row[0] for row in db.execute("SELECT id FROM devices ORDER BY id")
                    )
                principal = ConsolePrincipal("operator", devices)
            else:
                assert device is not None
                principal = ConsolePrincipal("collector", (device,))
            return self.response(
                self.console.read(
                    path.removeprefix("/v1/console/"), env.get("QUERY_STRING", ""), principal
                )
            )
        if method == "GET" and path == "/v1/status":
            counts = ops.upload_counts(device)
            return self.response(
                {
                    "schema": "stpd/hub-status-v1",
                    "version": 1,
                    "counts": counts,
                    "paused": ops.paused(),
                }
            )
        if method == "GET" and path in {"/v1/uploads", "/v1/incidents"}:
            query = parse_qs(env.get("QUERY_STRING", ""), strict_parsing=True)
            if set(query) - {"limit", "offset"} or any(len(value) != 1 for value in query.values()):
                raise BoundaryError("hub", "invalid_pagination")
            limit, offset = int(query.get("limit", ["100"])[0]), int(query.get("offset", ["0"])[0])
            if not 1 <= limit <= 100 or offset < 0:
                raise BoundaryError("hub", "invalid_pagination")
            statuses = ("quarantined", "transfer_failed") if path.endswith("incidents") else None
            items = [
                self.upload_status(row)
                for row in ops.uploads(device, limit=limit, offset=offset, statuses=statuses)
            ]
            return self.response(
                {
                    "items": items,
                    "limit": limit,
                    "offset": offset,
                    "next_offset": offset + limit if len(items) == limit else None,
                }
            )
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
        artifact = re.fullmatch(r"/v1/artifacts/([a-f0-9]{64})(?:/payloads/([a-z0-9_]+))?", path)
        if artifact and method == "GET":
            manifest = self.service.store.get_manifest(artifact[1])
            if not admin and manifest.kind not in RESULT_KINDS:
                raise BoundaryError("hub", "unauthorized")
            if artifact[2] is None:
                return self.response(decode_json(manifest.to_bytes()))
            return (
                "200 OK",
                "application/octet-stream",
                self.service.store.read_payload(manifest.payload(artifact[2])),
            )
        if method == "GET" and path == "/v1/jobs":
            fields = {
                "id",
                "kind",
                "input_id",
                "status",
                "max_seconds",
                "reserved_units",
                "attempt_id",
                "provider_ref",
                "result",
            }
            return self.response(
                {
                    "items": [
                        {key: value for key, value in row.items() if key in fields}
                        for row in ops.jobs()
                    ]
                }
            )
        if not admin:
            raise BoundaryError("hub", "unauthorized")
        if method == "POST" and path == "/v1/jobs":
            body = self.body(env)
            job_id = ops.enqueue(
                body["kind"],
                body["input_id"],
                body["request_key"],
                max_seconds=body["max_seconds"],
                reserved_units=body["reserved_units"],
                budget_limit=self.budget_limit,
                options=body.get("options"),
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
        match = re.fullmatch(r"/v1/uploads/([a-f0-9]{32})/retry", path)
        if match and method == "POST":
            ops.retry_upload(match[1])
            return self.response({"retry_authorized": True})
        return self.response({"error": "not_found"}, "404 Not Found")
