"""Local CLI client for the already-owned workbench model service."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from ..canonical import canonical_json
from ..json_boundary import BoundaryError, decode_json, digest
from .developer import ProjectConfig
from .developer_server import running
from .hub_client import NoRedirect


def model_command(
    config: ProjectConfig,
    action: str,
    *,
    selection: str | None = None,
    artifact: str | None = None,
) -> dict[str, Any]:
    current = running(config)
    if current is None:
        raise BoundaryError("local_model", "open_workbench_first")
    route = "/api/local-models"
    body = None
    if action == "status":
        route += "/status"
    elif action == "readiness":
        if not selection:
            raise BoundaryError("local_model", "selection_required")
        route += "/readiness?" + urlencode({"selection_id": selection})
    elif action == "start":
        if not selection:
            raise BoundaryError("local_model", "selection_required")
        route += "/start"
        body = {"selection_id": selection}
    elif action == "download":
        route += "/download"
        body = {"artifact_id": digest(artifact, "local_model.artifact")}
    elif action in {"human", "shadow", "one_step", "auto", "stop"}:
        route += "/command"
        body = {"action": action}
    elif action != "catalog":
        raise BoundaryError("local_model", "unsupported_local_command")
    request = Request(
        f"http://127.0.0.1:{current['port']}" + route,
        data=canonical_json(body).encode() if body is not None else None,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + current["control_token"],
        },
    )
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=25) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError
        result = decode_json(raw)
        if not isinstance(result, dict) or result.get("schema") != "stpd/local-models-v1":
            raise ValueError
        return result
    except (OSError, ValueError):
        raise BoundaryError(
            "local_model", "workbench_request_failed_check_status_before_retry"
        ) from None
