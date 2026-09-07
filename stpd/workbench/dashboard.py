"""Stable local dashboard projection and escaped static HTML renderer."""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from ..artifact_contracts import Manifest
from ..storage.registry import Registry
from ..storage.store import ArtifactStore
from .analysis import AnalysisReport, analyze

SCHEMA = "stpd/local-dashboard-v1"
SECTIONS = (
    "Overview",
    "Datasets",
    "Experiments",
    "Runs",
    "Models",
    "Evaluations",
    "Analysis",
    "Lineage",
    "Artifacts",
    "System Readiness",
)
_PRIVATE_KEY = re.compile(r"(?:secret|token|password|credential|private|filename|path)$", re.I)


def _safe_value(value: Any, *, key: str = "") -> Any:
    """Keep manifest metadata useful while dropping path/secret-shaped fields."""
    if _PRIVATE_KEY.search(key):
        return "[redacted]"
    if isinstance(value, Mapping):
        return {
            str(name): _safe_value(child, key=str(name)) for name, child in sorted(value.items())
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(child, key=key) for child in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and (
            value.startswith(("/", "~", "file://"))
            or re.match(r"^[A-Za-z]:[\\/]", value) is not None
        ):
            return "[redacted]"
        return value
    return str(value)


def _manifest_row(manifest: Manifest, registry: Registry) -> dict[str, Any]:
    info = manifest.parameters.value()
    public_parameters = _safe_value(info)
    return {
        "artifact_id": manifest.artifact_id,
        "kind": manifest.kind,
        "producer": {
            "source_revision": manifest.producer.source_revision,
            "uv_lock_sha256": manifest.producer.uv_lock_sha256,
        },
        "parameters": public_parameters,
        "parents": [
            {"role": parent.role, "artifact_id": parent.artifact_id}
            for parent in sorted(manifest.parents)
        ],
        "payloads": [
            {
                "role": payload.role,
                "sha256": payload.sha256,
                "size": payload.size,
                "media_type": payload.media_type,
            }
            for payload in sorted(manifest.payloads)
        ],
        "cached": registry.is_cached(manifest.artifact_id),
    }


def _section_rows(manifests: tuple[Manifest, ...], kind: str) -> list[dict[str, Any]]:
    return [
        {
            "artifact_id": manifest.artifact_id,
            "kind": manifest.kind,
            "parameters": _safe_value(manifest.parameters.value()),
        }
        for manifest in manifests
        if manifest.kind == kind
    ]


@dataclass(frozen=True)
class DashboardProjection:
    """JSON-ready projection with a fixed, versioned section inventory."""

    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json.loads(json.dumps(self.payload, sort_keys=True, separators=(",", ":"))),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def project(
    registry: Registry,
    store: ArtifactStore,
    *,
    analysis: AnalysisReport | None = None,
) -> DashboardProjection:
    """Build a deterministic dashboard projection from Registry/ArtifactStore interfaces."""
    manifests = registry.manifests()
    by_kind = Counter(manifest.kind for manifest in manifests)
    analysis_report = analysis or analyze(registry, store)
    lineage = [
        {
            "child": manifest.artifact_id,
            "parent": parent.artifact_id,
            "role": parent.role,
        }
        for manifest in manifests
        for parent in sorted(manifest.parents)
    ]
    sections: dict[str, Any] = {
        "Overview": {
            "artifact_count": len(manifests),
            "counts_by_kind": {key: by_kind[key] for key in sorted(by_kind)},
            "analysis_schema": analysis_report.payload.get("schema"),
        },
        "Datasets": _section_rows(manifests, "dataset"),
        "Experiments": _section_rows(manifests, "experiment"),
        "Runs": _section_rows(manifests, "run"),
        "Models": _section_rows(manifests, "model"),
        "Evaluations": _section_rows(
            tuple(
                m
                for m in manifests
                if m.artifact_id not in analysis_report.payload["sealed_evaluations_omitted"]
            ),
            "offline_evaluation",
        )
        + _section_rows(manifests, "live_evaluation"),
        "Analysis": analysis_report.to_dict(),
        "Lineage": lineage,
        "Artifacts": [_manifest_row(manifest, registry) for manifest in manifests],
        "System Readiness": {
            "status": "projection_ready",
            "registry_indexed": True,
            "artifact_store_readable": True,
            "scientific_verdict": "not_claimed",
            "non_claims": [
                "A dashboard projection does not establish data admission, runtime "
                "qualification, or model quality.",
                "Readiness here means only that the local registry projection was built.",
            ],
        },
    }
    return DashboardProjection(
        {
            "schema": SCHEMA,
            "sections": {name: sections[name] for name in SECTIONS},
            "section_order": list(SECTIONS),
        }
    )


def render_html(projection: DashboardProjection) -> str:
    """Render self-contained HTML with escaped JSON values and no external assets."""
    payload = projection.to_dict()
    blocks: list[str] = []
    for section in payload["section_order"]:
        encoded = json.dumps(
            payload["sections"][section], ensure_ascii=False, indent=2, sort_keys=True
        )
        blocks.append(
            f'<section id="{html.escape(section.lower().replace(" ", "-"), quote=True)}">'
            f"<h2>{html.escape(section)}</h2>"
            f"<pre>{html.escape(encoded)}</pre></section>"
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>STPD Local Workbench</title></head><body><h1>STPD Local Workbench</h1>"
        f"<p>Projection schema: {html.escape(str(payload['schema']))}</p>"
        + "".join(blocks)
        + "</body></html>"
    )
