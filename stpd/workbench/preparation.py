"""Explicit controller preparation; the worker never chooses its own scientific inputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from ..artifact_contracts import Producer
from ..fullrun.data import admit, publish_dataset, publish_source
from ..fullrun.features import compile_features, publish_model_view
from ..fullrun.fixtures import SyntheticSourceAdapter, synthetic_bundle
from ..fullrun.representation import FullRunSerializer
from ..json_boundary import BoundaryError
from ..qwen.fake_backend import DeterministicFakeQwenBackend
from ..storage.store import ManifestArtifactStore
from ..workers.contracts import TrainingConfig, prepare_run, prepare_training_input


def prepare(
    store: ManifestArtifactStore,
    runtime: Producer,
    *,
    dataset_id: str | None,
    fixture: bool,
    config: TrainingConfig,
    profile: str = "standard",
    qwen_snapshot: Path | None = None,
    control: Literal["pretrained", "random"] = "pretrained",
    random_seed: int | None = None,
    protocol_id: str | None = None,
) -> dict[str, Any]:
    if fixture == (dataset_id is not None):
        raise BoundaryError("prepare", "choose_exact_dataset_or_explicit_fixture")
    if fixture:
        source, projection = publish_source(
            store, synthetic_bundle(runs=6), SyntheticSourceAdapter(), runtime
        )
        dataset = publish_dataset(store, admit((projection,)), (source,), runtime)
        dataset_id = dataset.artifact_id
    if dataset_id is None:
        raise BoundaryError("prepare", "dataset_required")
    view = publish_model_view(store, dataset_id, FullRunSerializer(profile), runtime)
    backend: Any
    if qwen_snapshot is None:
        if not fixture:
            raise BoundaryError("prepare", "explicit_qwen_snapshot_required")
        backend = DeterministicFakeQwenBackend(8)
    else:
        from ..qwen.real_backend import RealQwenBackend

        backend = RealQwenBackend(
            qwen_snapshot, control=control, random_seed=random_seed, device=config.device
        )
    features = compile_features(store, view.artifact_id, backend, runtime)
    training = prepare_training_input(
        store, features.artifact_id, runtime, config, protocol_id=protocol_id
    )
    experiment, run = prepare_run(store, training.artifact_id, runtime)
    return {
        "dataset_id": dataset_id,
        "model_view_id": view.artifact_id,
        "feature_set_id": features.artifact_id,
        "training_input_id": training.artifact_id,
        "experiment_id": experiment.artifact_id,
        "run_id": run.artifact_id,
        "scope": training.parameters.value()["scope"],
    }
