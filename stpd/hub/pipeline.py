"""CPU orchestration of existing strict research services; no training semantics."""

from __future__ import annotations

from typing import Any

from ..artifact_contracts import Producer
from ..cloud_jobs.contracts import FeatureJobSpec, publish_feature_job
from ..fullrun.data import admit, load_dataset, publish_dataset, publish_received_source
from ..fullrun.features import publish_model_view
from ..fullrun.representation import FullRunSerializer
from ..json_boundary import BoundaryError
from ..storage.store import ArtifactStore


def build_dataset(
    store: ArtifactStore, received_ids: tuple[str, ...], producer: Producer, *, seed: int = 0
) -> dict[str, Any]:
    """Freeze an explicit inventory, preserving failed sources even if admission fails."""
    if not received_ids or len(set(received_ids)) != len(received_ids):
        raise BoundaryError("pipeline", "explicit_unique_received_inventory_required")
    sources, projections = [], []
    for identity in sorted(received_ids):
        source, projection = publish_received_source(store, identity, producer)
        sources.append(source)
        projections.append(projection)
    dataset = admit(tuple(projections), seed=seed)
    manifest = publish_dataset(store, dataset, tuple(sources), producer)
    _, reloaded = load_dataset(store, manifest.artifact_id)
    if reloaded != dataset:
        raise BoundaryError("pipeline", "dataset_reload_mismatch")
    return {
        "dataset_id": manifest.artifact_id,
        "source_ids": [source.artifact_id for source in sources],
        "records": len(dataset.records),
        "scope": dataset.scope,
        "splits": dataset.splits.value(),
    }


def prepare_features(
    store: ArtifactStore, dataset_id: str, spec: FeatureJobSpec, producer: Producer
) -> dict[str, str]:
    view = publish_model_view(store, dataset_id, FullRunSerializer(), producer)
    job = publish_feature_job(store, view.artifact_id, producer, spec)
    return {"model_view_id": view.artifact_id, "feature_job_id": job.artifact_id}
