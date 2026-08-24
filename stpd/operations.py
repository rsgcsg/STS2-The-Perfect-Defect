"""Fail-closed local readiness checks for the pre-Qwen handoff."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .host_runtime_client import load_host_runtime_pin
from .package_identity import validate_installed_package
from .qwen.l1 import inspect_cache, is_weight_file, load_pin


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    details: dict[str, Any]


def _run(command: list[str], *, cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "command failed")
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_doctor(
    root: Path,
    *,
    qwen_cache: Path | None = None,
    require_qwen_cache: bool = False,
    host_runtime: Path | None = None,
    candidate: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    checks: list[DoctorCheck] = []

    python_ok = sys.version_info[:2] == (3, 11)
    checks.append(DoctorCheck("python", "pass" if python_ok else "fail", {
        "required": ">=3.11,<3.12", "actual": sys.version.split()[0]
    }))

    revision = _run(["git", "rev-parse", "HEAD"], cwd=root)
    clean = not _run(["git", "status", "--porcelain"], cwd=root)
    checks.append(DoctorCheck("stpd_source", "pass" if clean else "fail", {
        "revision": revision, "worktree": "clean" if clean else "dirty"
    }))

    lock = root / "uv.lock"
    checks.append(DoctorCheck("uv_lock", "pass" if lock.is_file() else "fail", {
        "sha256": _sha256(lock) if lock.is_file() else None
    }))

    schemas = sorted((root / "schemas").glob("*.schema.json"))
    required_schemas = {
        "data-manifest-v0.schema.json",
        "experiment-manifest-v0.schema.json",
        "human-collection-campaign-v1.schema.json",
        "human-collection-profile-v1.schema.json",
        "model-artifact-manifest-v0.schema.json",
        "research-action-v0.schema.json",
        "research-state-v0.schema.json",
        "research-transition-v0.schema.json",
    }
    try:
        schema_documents = [json.loads(path.read_text(encoding="utf-8")) for path in schemas]
        schema_ids = [document["$id"] for document in schema_documents]
        schemas_ok = (
            required_schemas.issubset(path.name for path in schemas)
            and all(
                document.get("$schema")
                == "https://json-schema.org/draft/2020-12/schema"
                for document in schema_documents
            )
            and len(schema_ids) == len(set(schema_ids))
        )
    except (json.JSONDecodeError, KeyError):
        schemas_ok = False
        schema_ids = []
    checks.append(DoctorCheck("schemas", "pass" if schemas_ok else "fail", {
        "count": len(schemas), "unique_ids": len(set(schema_ids))
    }))

    tracked = _run(["git", "ls-files"], cwd=root).splitlines()
    tracked_weights = sorted(value for value in tracked if is_weight_file(value))
    checks.append(DoctorCheck("repository_weights", "pass" if not tracked_weights else "fail", {
        "tracked_weight_files": tracked_weights
    }))

    pin = load_pin()
    if qwen_cache is not None:
        try:
            artifact = inspect_cache(qwen_cache.expanduser(), pin)
            qwen_status = "pass"
            qwen_details = artifact.to_dict()
        except Exception as exc:  # classified in the machine report
            qwen_status = "fail"
            qwen_details = {"error": str(exc)}
    elif require_qwen_cache:
        qwen_status, qwen_details = "fail", {"error": "Qwen L1 cache is required"}
    else:
        qwen_status, qwen_details = "not_requested", pin.to_dict()
    checks.append(DoctorCheck("qwen_l1", qwen_status, qwen_details))

    if host_runtime is not None:
        host_runtime = host_runtime.resolve()
        try:
            details = validate_installed_package(
                host_runtime,
                load_host_runtime_pin(),
                required_paths=(
                    "tools/managed-exact.mjs",
                    "tools/managed-pe-driver.mjs",
                    "consumers/python/sts2_headless/__init__.py",
                ),
            )
            status = "pass"
            if candidate is not None:
                output = _run([
                    "node", str(host_runtime / "tools" / "managed-exact.mjs"),
                    "audit", "--candidate",
                    str(candidate.resolve()),
                ], cwd=root)
                details["candidate_audit"] = json.loads(output)
        except Exception as exc:
            status, details = "fail", {"error": str(exc)}
        checks.append(DoctorCheck("host_runtime", status, details))
    elif candidate is not None:
        checks.append(DoctorCheck("host_runtime", "fail", {
            "error": "candidate audit requires --host-runtime"
        }))

    free = shutil.disk_usage(root).free
    checks.append(DoctorCheck("disk", "pass" if free >= 1024**3 else "fail", {
        "free_bytes": free, "minimum_bytes": 1024**3
    }))
    failed = [check.name for check in checks if check.status == "fail"]
    return {
        "schema": "stpd/pre-qwen-doctor-v0",
        "status": "pass" if not failed else "fail",
        "checks": [asdict(check) for check in checks],
        "failed": failed,
        "non_claims": [
            "Doctor validates local identities and files; it does not load Qwen weights.",
            "A candidate audit is build provenance, not gameplay qualification.",
        ],
    }
