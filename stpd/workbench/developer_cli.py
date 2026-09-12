"""Unified developer entry: python -m stpd.workbench project --help."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from ..json_boundary import BoundaryError, decode_json, digest, text
from .developer import DEFAULT_CONFIG, ROOT, ProjectConfig, doctor, setup
from .developer_server import _local_request, open_project, running, serve, stop_project
from .hub_client import HubClient


def inspect_policy(path: Path) -> dict[str, Any]:
    """Inspect an existing immutable selection without loading weights or acquiring control."""
    raw = path.read_bytes()
    value = decode_json(raw)
    if (
        not isinstance(value, dict)
        or value.get("schema") != "sts2.policy-runtime/policy-manifest-1"
    ):
        raise BoundaryError("policy", "unsupported_manifest")
    artifact, adapter = value.get("artifact"), value.get("adapter")
    if not isinstance(artifact, dict) or not isinstance(adapter, dict):
        raise BoundaryError("policy", "invalid_manifest")
    if adapter.get("protocol") != "sts2.policy-runtime/decision-only-ndjson-1":
        raise BoundaryError("policy", "unsupported_adapter_protocol")
    checkpoint = digest(artifact.get("sha256"), "policy.checkpoint")
    code = digest(adapter.get("code_sha256"), "policy.code")
    return {
        "schema": "stpd/policy-inspection-v1",
        "status": "manifest_inspected",
        "manifest_id": text(value.get("manifest_id"), "policy.manifest_id"),
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "checkpoint_sha256": checkpoint,
        "adapter_code_sha256": code,
        "loaded": False,
        "activated": False,
        "non_claims": ["weights available", "current runtime compatible", "model quality"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("setup", "doctor", "open", "status", "stop", "serve", "download", "policy"),
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state-dir", type=Path, default=ROOT / ".local/developer")
    parser.add_argument("--hub-url", default="")
    parser.add_argument("--platform-url", default="")
    parser.add_argument("--delivery-config", type=Path)
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="only configure; doctor still requires the exact installed tools",
    )
    parser.add_argument(
        "--replace-config",
        action="store_true",
        help="explicitly replace local settings with these setup arguments",
    )
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--artifact")
    parser.add_argument(
        "--role", action="append", help="own payload role, repeat for multiple roles"
    )
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        result: Any
        if args.command == "setup":
            result = setup(
                args.config.resolve(),
                state_dir=args.state_dir,
                hub_url=args.hub_url,
                platform_url=args.platform_url,
                delivery_config=args.delivery_config,
                install=not args.skip_install,
                replace_config=args.replace_config,
            )
        elif args.command == "policy":
            if args.manifest is None:
                raise BoundaryError("policy", "manifest_required")
            result = inspect_policy(args.manifest)
        else:
            config = ProjectConfig.load(args.config)
            if args.command == "doctor":
                result = doctor(config)
            elif args.command == "open":
                result = open_project(args.config.resolve(), browser=not args.no_browser)
            elif args.command == "stop":
                result = stop_project(config)
            elif args.command == "serve":
                result = serve(config)
            elif args.command == "status":
                runtime = running(config)
                result = (
                    {"status": "not_running"}
                    if runtime is None
                    else _local_request(f"http://127.0.0.1:{runtime['port']}/api/status")
                )
            else:
                if not args.artifact or not config.hub_url:
                    raise BoundaryError("download", "artifact_and_hub_required")
                result = HubClient(config.hub_url).download(
                    args.artifact,
                    config.state_dir / "downloads",
                    tuple(args.role) if args.role is not None else None,
                )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1 if result.get("status") == "BLOCKED" else 0
    except (BoundaryError, OSError, ValueError, subprocess.SubprocessError) as error:
        code = error.code if isinstance(error, BoundaryError) else type(error).__name__
        print(json.dumps({"status": "FAIL", "code": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
