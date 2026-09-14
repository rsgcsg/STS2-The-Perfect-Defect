"""One public artifact policy; project membership never opens sealed research results.

Research-owner store operations are separate from HTTP sharing. Legacy machine tokens
retain result-only downloads; immutable evidence archives need an explicit collection grant.
"""

from __future__ import annotations

from ..artifact_contracts import Manifest
from ..json_boundary import BoundaryError
from ..storage.store import ArtifactStore

RESULT_KINDS = frozenset(
    {
        "model",
        "checkpoint",
        "run_result",
        "offline_evaluation",
        "live_evaluation",
        "performance",
        "analysis",
    }
)
PROJECT_KINDS = RESULT_KINDS | {"dataset", "training_input", "experiment", "run"}
POLICY_VERSION = "stpd/project-sharing-v1"


def project_member(principal: object) -> bool:
    return getattr(principal, "role", None) in {"member", "admin"}


def sealed_reason(manifest: Manifest) -> str | None:
    info = manifest.parameters.value()
    if manifest.kind in {"gold_tasks", "gold_labels"}:
        return "sealed_research_artifact"
    if info.get("partition") in {"test", "gold_test"} or info.get("sealed_test") is True:
        return "sealed_research_artifact"
    if manifest.kind == "offline_evaluation" and info.get("partition") != "dev":
        return "evaluation_partition_not_public"
    return None


def discoverable(manifest: Manifest) -> bool:
    return manifest.kind in PROJECT_KINDS and sealed_reason(manifest) is None


def lineage(store: ArtifactStore, manifest: Manifest) -> tuple[Manifest, ...]:
    """Bounded exact manifest closure, never a bucket scan or implicit payload download."""
    pending = [manifest.artifact_id]
    queued = {manifest.artifact_id}
    found: dict[str, Manifest] = {}
    while pending:
        identity = pending.pop()
        item = manifest if identity == manifest.artifact_id else store.get_manifest(identity)
        found[identity] = item
        for parent in item.parents:
            if parent.artifact_id in queued:
                continue
            if len(queued) >= 512:
                raise BoundaryError("sharing", "lineage_limit")
            queued.add(parent.artifact_id)
            pending.append(parent.artifact_id)
    return tuple(found.values())


def require_artifact_access(
    manifest: Manifest,
    *,
    project_member: bool = False,
    payload_role: str | None = None,
    store: ArtifactStore | None = None,
) -> None:
    allowed = PROJECT_KINDS if project_member else RESULT_KINDS
    if manifest.kind not in allowed:
        raise BoundaryError("hub", "unauthorized")
    # Check exact parent manifests when serving bytes. A result cannot launder sealed
    # evaluation/Gold content by being wrapped in an otherwise public analysis artifact.
    nodes = (manifest,) if store is None else lineage(store, manifest)
    if any(sealed_reason(item) for item in nodes):
        raise BoundaryError("hub", "unauthorized")
    if payload_role is not None:
        manifest.payload(payload_role)
