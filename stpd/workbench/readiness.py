"""Deterministic read-only evidence classification for an exact checked-out source."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..json_boundary import decode_json
from .control import source_identity

EXTERNAL = {
    "external_object_store": "EXTERNAL INPUT REQUIRED",
    "external_gpu": "EXTERNAL INPUT REQUIRED",
    "platform_full_run": "PLATFORM FINAL BUNDLE REQUIRED",
    "human_gold": "HUMAN REQUIRED",
    "real_sts2_live_evaluation": "HUMAN REQUIRED",
    "scientific_campaign": "NOT SCIENTIFICALLY CLAIMED",
}
ENGINEERING = (
    "governance",
    "portable_ci_contract",
    "research_contracts",
    "data_representation",
    "artifact_registry",
    "worker_checkpoint",
    "model_evaluation",
    "analysis_dashboard",
    "gold_campaign_tooling",
)


def readiness(root: Path, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify explicit receipts; absent/stale receipts never imply a test pass.

    Evidence is a local reviewed receipt, not a cryptographic attestation. The release
    owner independently verifies the referenced hosted CI run and exact checkout.
    """
    runtime = source_identity(root)
    value = evidence or {}
    exact = (
        value.get("schema") == "stpd/prefullrun-qualification-v1"
        and value.get("producer") == runtime.to_dict()
    )
    portable = exact and value.get("portable") == "PASS"
    e2e = value.get("e2e", {})
    end_to_end = (
        exact
        and isinstance(e2e, dict)
        and e2e.get("verdict") == "CPU_E2E_PASS"
        and e2e.get("producer") == runtime.to_dict()
    )
    ci = value.get("ci", {})
    hosted = (
        exact
        and isinstance(ci, dict)
        and ci.get("head_sha") == runtime.source_revision
        and isinstance(ci.get("run_id"), int)
        and ci.get("conclusion") == "success"
        and ci.get("jobs")
        == {name: "success" for name in ("linux-portable", "windows-portable", "locked-python")}
    )
    passed = portable and end_to_end and hosted
    categories = {
        name: "AI ENGINEERING PASS" if passed else "EVIDENCE REQUIRED" for name in ENGINEERING
    }
    categories.update(EXTERNAL)
    return {
        "schema": "stpd/prefullrun-readiness-v1",
        "producer": runtime.to_dict(),
        "verdict": "STPD_PRE_FULLRUN_AI_ENGINEERING_READY" if passed else "EVIDENCE_REQUIRED",
        "categories": categories,
        "receipts": {
            "exact_source": exact,
            "portable": portable,
            "clean_cpu_e2e": end_to_end,
            "linux_windows_locked_python": hosted,
        },
        "evidence_trust": "reviewed local receipt; verify hosted run independently",
        "non_claims": [
            "real Full-Run Dataset",
            "Human Gold labels",
            "S3 deployment qualified",
            "GPU provider qualified",
            "Qwen advantage",
            "model quality",
            "scientific campaign complete",
            "real STS2 live evaluation",
        ],
    }


def read_receipt(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    value = decode_json(path.read_bytes())
    if not isinstance(value, dict):
        from ..json_boundary import BoundaryError

        raise BoundaryError("readiness", "receipt_must_be_object")
    return value
