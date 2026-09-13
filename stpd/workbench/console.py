"""Read-only local projections of the Platform outbox and authenticated Hub APIs.

The local console uses the device credential on the server, never a browser token.
Caches retain explicitly dated observations; they do not reinterpret owner facts.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

from ..json_boundary import BoundaryError
from .developer import ProjectConfig
from .hub_client import HubClient


def observed_at() -> str:
    return datetime.now(UTC).isoformat()


def pagination(query: str) -> tuple[int, int]:
    try:
        values = parse_qs(query, strict_parsing=True, max_num_fields=2)
        if set(values) - {"limit", "offset"} or any(len(v) != 1 for v in values.values()):
            raise ValueError
        limit = int(values.get("limit", ["25"])[0])
        offset = int(values.get("offset", ["0"])[0])
        if not 1 <= limit <= 100 or not 0 <= offset <= 2**31 - 1:
            raise ValueError
    except ValueError:
        raise BoundaryError("console", "invalid_pagination") from None
    return limit, offset


class ProjectionCache:
    """Small process-local observation cache; failures mark the retained result stale."""

    def __init__(self, *, ttl: float = 5, maximum: int = 64) -> None:
        self.ttl = ttl
        self.maximum = maximum
        self.values: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self.lock = threading.Lock()

    def read(self, key: str, loader: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        # The lock bounds concurrent refreshes; loaders all have explicit timeouts.
        with self.lock:
            previous = self.values.get(key)
            if previous and time.monotonic() - previous[0] < self.ttl:
                self.values.move_to_end(key)
                return copy.deepcopy(previous[1])
            try:
                value = loader()
                if not isinstance(value, dict):
                    raise BoundaryError("console", "invalid_response")
                value = {**value, "observed_at": value.get("observed_at") or observed_at()}
            except (BoundaryError, OSError, ValueError, subprocess.SubprocessError) as error:
                code = error.code if isinstance(error, BoundaryError) else "observation_unavailable"
                value = {
                    **(previous[1] if previous else {}),
                    "status": "stale"
                    if previous and "observed_at" in previous[1]
                    else "unavailable",
                    "error_code": code,
                    "checked_at": observed_at(),
                }
            self.values[key] = (time.monotonic(), value)
            self.values.move_to_end(key)
            while len(self.values) > self.maximum:
                self.values.popitem(last=False)
            return copy.deepcopy(value)


class LocalConsole:
    def __init__(
        self,
        config: ProjectConfig,
        hub: HubClient | None,
        environment: Callable[[], dict[str, str]],
        delivery_process: Callable[[], str],
        identity: dict[str, Any],
    ) -> None:
        self.config = config
        self.hub = hub
        self.environment = environment
        self.delivery_process = delivery_process
        self.identity = identity
        # Cloud unavailability must never serialize behind or block a local refresh.
        self.local_cache = ProjectionCache()
        self.cloud_cache = ProjectionCache()

    def owner_status(
        self, *, limit: int = 25, offset: int = 0, delivery_id: str | None = None
    ) -> dict[str, Any]:
        if self.config.delivery_config is None:
            return {
                "status": "not_configured",
                "sessions": [],
                "total": 0,
                "counts": {},
                "limit": limit,
                "offset": offset,
                "next_offset": None,
            }
        command = [
            sys.executable,
            "-I",
            "-m",
            "sts2_platform_evidence.delivery_cli",
            "status",
            "--config",
            str(self.config.delivery_config),
            "--summary",
            "--limit",
            str(limit),
            "--offset",
            str(offset),
        ]
        if delivery_id is not None:
            command.extend(["--delivery-id", delivery_id])
        result = subprocess.run(
            command,
            cwd=self.config.state_dir,
            env=self.environment(),
            capture_output=True,
            timeout=4,
            check=False,
        )
        if result.returncode != 0 or len(result.stdout) > 8 * 1024 * 1024:
            raise BoundaryError("console", "owner_status_unavailable")
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or value.get("schema") != "sts2.evidence/delivery-status-2":
            raise BoundaryError("console", "unsupported_owner_projection")
        return value

    def local_status(
        self, *, limit: int = 25, offset: int = 0, delivery_id: str | None = None
    ) -> dict[str, Any]:
        return self.local_cache.read(
            f"{limit}:{offset}:{delivery_id}",
            lambda: self.owner_status(limit=limit, offset=offset, delivery_id=delivery_id),
        )

    def remote(
        self, route: str, *, limit: int | None = None, offset: int | None = None
    ) -> dict[str, Any]:
        if self.hub is None:
            return {"status": "not_configured"}
        return self.cloud_cache.read(
            f"{route}:{limit}:{offset}",
            lambda: (
                self.hub.get("/v1/console/" + route, limit=limit, offset=offset) if self.hub else {}
            ),
        )

    @staticmethod
    def collection(row: dict[str, Any]) -> dict[str, Any]:
        # The owner summary is the only recording interpretation consumed here.
        fields = (
            "id",
            "session_id",
            "upload_id",
            "content_id",
            "status",
            "stage",
            "attempts",
            "retry_at",
            "error",
            "receipt",
            "summary",
            "summary_status",
            "observed_at",
            "transport_observed_at",
            "archive_bytes",
        )
        item = {name: row.get(name) for name in fields}
        item["summary_status"] = row.get("summary_status") or (
            "available" if isinstance(row.get("summary"), dict) else "not_indexed"
        )
        item["research"] = {"status": "not_assessed"}
        return item

    def collections(self, limit: int, offset: int) -> dict[str, Any]:
        source = self.local_status(limit=limit, offset=offset)
        return {
            "schema": "stpd/console-v1",
            "observed_at": source.get("observed_at"),
            "status": source.get("status", "available"),
            "items": [self.collection(row) for row in source.get("sessions", [])],
            "limit": limit,
            "offset": offset,
            "total": source.get("total"),
            "next_offset": source.get("next_offset"),
            "counts": source.get("counts", {}),
            "delivery_process": self.delivery_process(),
        }

    def collection_detail(self, identity: str) -> dict[str, Any]:
        source = self.local_status(delivery_id=identity)
        rows = source.get("sessions", [])
        if not rows:
            if source.get("status") in {"unavailable", "stale"}:
                raise BoundaryError("console", "owner_status_unavailable")
            raise BoundaryError("console", "record_not_found")
        row = self.collection(rows[0])
        if row["id"] != identity:
            raise BoundaryError("console", "owner_identity_mismatch")
        upload_id = row.get("upload_id")
        if isinstance(upload_id, str) and re.fullmatch(r"[a-f0-9]{32}", upload_id):
            cloud = self.remote("collections/" + upload_id)
            remote_row = cloud.get("item", {})
            if remote_row and remote_row.get("content_id") != row.get("content_id"):
                raise BoundaryError("console", "remote_identity_mismatch")
            row["remote"] = {
                "status": cloud.get("status", "available"),
                "observed_at": cloud.get("observed_at"),
            }
            for name in (
                "timeline",
                "timeline_truncated",
                "verify_attempts",
                "research",
                "evidence_id",
                "archive_bytes",
            ):
                if name in remote_row:
                    row[name] = remote_row[name]
        return {
            "schema": "stpd/console-v1",
            "observed_at": source.get("observed_at"),
            "status": source.get("status", "available"),
            "item": row,
        }

    def overview(self) -> dict[str, Any]:
        # Both owners remain separate; the UI can render local collections independently.
        local = self.collections(3, 0)
        cloud = self.remote("overview")
        statuses = local.get("counts", {})
        source = self.local_status(limit=3, offset=0)
        quality = source.get("quality", {})
        return {
            "schema": "stpd/console-v1",
            "observed_at": local.get("observed_at"),
            "status": local.get("status", "available"),
            "counts": {"pending": statuses.get("pending"), "verified": statuses.get("verified")},
            "quality": quality,
            "quality_coverage": ("统计来自全部已建立的可信摘要；缺失摘要不被当作零失败。"),
            "recent": local["items"],
            "cloud": cloud,
            "delivery_process": self.delivery_process(),
            "access": {"role": "device", "read_only": True},
        }

    def catalog(self, view: str, limit: int, offset: int) -> dict[str, Any]:
        result = self.remote(view, limit=limit, offset=offset)
        if view == "models":
            for row in result.get("items", []):
                identity = row.get("artifact_id")
                row["local_download"] = self.local_download(identity)
        return result

    def local_download(self, identity: object) -> bool:
        if not isinstance(identity, str) or re.fullmatch(r"[a-f0-9]{64}", identity) is None:
            return False
        directory = self.config.state_dir / "downloads" / identity
        receipt = directory / "download.json"
        if directory.is_symlink() or receipt.is_symlink() or not receipt.is_file():
            return False
        try:
            if receipt.stat().st_size > 1024 * 1024:
                return False
            value = json.loads(receipt.read_bytes())
            return bool(
                isinstance(value, dict)
                and value.get("artifact_id") == identity
                and value.get("schema") == "stpd/result-download-v1"
            )
        except (OSError, ValueError):
            return False

    def system(self) -> dict[str, Any]:
        remote = self.remote("system")
        result: dict[str, Any] = {
            "schema": "stpd/console-v1",
            "observed_at": observed_at(),
            "identity": self.identity,
            "delivery_status": self.delivery_process(),
            "cloud_status": remote.get("status", "available"),
            "access": {"role": "device", "read_only": True},
            "cloud": remote,
        }
        if self.config.platform_url:
            # Configuration proves an endpoint, not that it serves a Workbench HTML page.
            result["platform_endpoint"] = {
                "url": self.config.platform_url,
                "label": "Platform 本地端点 ↗",
                "capability": "not_probed",
            }
        return result

    def route(self, path: str, query: str) -> dict[str, Any]:
        limit, offset = pagination(query)
        if path == "overview":
            return self.overview()
        if path == "collections":
            return self.collections(limit, offset)
        match = re.fullmatch(r"collections/([a-f0-9]{64})", path)
        if match:
            return self.collection_detail(match[1])
        if path in {"datasets", "models", "jobs"}:
            return self.catalog(path, limit, offset)
        if path == "system":
            return self.system()
        raise BoundaryError("console", "route_not_found")
