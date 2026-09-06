"""Frozen training inputs and run identities, independent of provider or registry."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from ..artifact_contracts import Manifest, Parent, Producer
from ..fullrun.features import LoadedFeatures, load_features
from ..json_boundary import BoundaryError, FrozenObject, object_fields, text, unsigned
from ..storage.store import ArtifactStore

TRAINING_SCHEMA = "stpd/training-input-v1"
RUN_SCHEMA = "stpd/research-run-v1"
ENTRYPOINT = "stpd.workers.worker:execute"


@dataclass(frozen=True)
class TrainingConfig:
    seed: int = 0
    epochs: int = 2
    max_steps: int | None = None
    learning_rate: float = 0.01
    weight_decay: float = 0.0
    head: str = "linear"
    device: str = "cpu"
    dtype: str = "float32"
    checkpoint_interval: int = 16
    candidate_order: str = "canonical"
    label_control: str = "observed"
    purpose: str = "engineering"

    def __post_init__(self) -> None:
        if unsigned(self.seed, "training.seed") >= 2**63:
            raise BoundaryError("training", "seed_out_of_range")
        if unsigned(self.epochs, "training.epochs") == 0:
            raise BoundaryError("training", "zero_epochs")
        if self.max_steps is not None and unsigned(self.max_steps, "training.max_steps") == 0:
            raise BoundaryError("training", "zero_step_budget")
        if unsigned(self.checkpoint_interval, "training.checkpoint_interval") == 0:
            raise BoundaryError("training", "zero_checkpoint_interval")
        for name in ("learning_rate", "weight_decay"):
            value = getattr(self, name)
            if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
                raise BoundaryError("training", "invalid_optimizer_config")
        if self.learning_rate == 0:
            raise BoundaryError("training", "zero_learning_rate")
        if self.head not in {"linear", "mlp"} or self.dtype != "float32":
            raise BoundaryError("training", "unsupported_model_config")
        if self.device != "cpu" and not (
            isinstance(self.device, str)
            and self.device.startswith("cuda:")
            and self.device[5:].isdigit()
        ):
            raise BoundaryError("training", "explicit_device_required")
        if self.candidate_order not in {"canonical", "permuted"}:
            raise BoundaryError("training", "unknown_candidate_control")
        if self.label_control not in {"observed", "permuted"}:
            raise BoundaryError("training", "unknown_label_control")
        if self.purpose not in {"engineering", "research"}:
            raise BoundaryError("training", "unknown_purpose")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def decode(cls, value: object) -> TrainingConfig:
        keys = set(cls.__dataclass_fields__)
        return cls(**object_fields(value, keys, "training.config"))


def _research_admission(
    store: ArtifactStore, features: LoadedFeatures, config: TrainingConfig, protocol_id: str | None
) -> None:
    if config.purpose == "engineering":
        return
    if protocol_id is None:
        raise BoundaryError("training", "frozen_protocol_required")
    protocol = store.get_manifest(protocol_id)
    info = protocol.parameters.value()
    if (
        protocol.kind != "protocol"
        or info.get("schema") != "stpd/fullrun-protocol-v1"
        or info.get("status") != "frozen"
        or features.manifest.parameters.value().get("scope") != "platform_qualified"
        or features.manifest.parameters.value().get("qwen", {}).get("model_id")
        == "stpd/deterministic-fake-qwen"
    ):
        raise BoundaryError("training", "research_admission_not_satisfied")
    if features.view.parent("dataset") != info.get("dataset_id"):
        raise BoundaryError("training", "protocol_dataset_mismatch")
    if features.view.artifact_id not in info.get("allowed_model_views", []):
        raise BoundaryError("training", "protocol_model_view_mismatch")
    if config.to_dict() not in info.get("allowed_training_configs", []):
        raise BoundaryError("training", "unfrozen_scientific_configuration")


def prepare_training_input(
    store: ArtifactStore,
    feature_id: str,
    producer: Producer,
    config: TrainingConfig,
    *,
    protocol_id: str | None = None,
) -> Manifest:
    features = load_features(store, feature_id)
    _research_admission(store, features, config, protocol_id)
    parents = [
        Parent("feature_set", feature_id),
        Parent("model_view", features.view.artifact_id),
        Parent("dataset", features.view.parent("dataset")),
    ]
    if protocol_id is not None:
        parents.append(Parent("protocol", protocol_id))
    manifest = Manifest(
        "training_input",
        producer,
        tuple(parents),
        parameters=FrozenObject.of(
            {
                "schema": TRAINING_SCHEMA,
                "entrypoint": ENTRYPOINT,
                "config": config.to_dict(),
                "qwen": features.manifest.parameters.value()["qwen"],
                "serializer": features.view.parameters.value()["serializer"],
                "scope": features.manifest.parameters.value()["scope"],
            }
        ),
    )
    store.publish(manifest)
    return manifest


def prepare_run(
    store: ArtifactStore, training_input_id: str, producer: Producer, *, replicate: str = "primary"
) -> tuple[Manifest, Manifest]:
    text(replicate, "run.replicate", maximum=128)
    training, config, _ = load_training_input(store, training_input_id, producer)
    experiment = Manifest(
        "experiment",
        producer,
        (Parent("training_input", training_input_id),),
        parameters=FrozenObject.of({"schema": "stpd/experiment-v1", "purpose": config.purpose}),
    )
    store.publish(experiment)
    run = Manifest(
        "run",
        producer,
        (Parent("experiment", experiment.artifact_id), Parent("training_input", training_input_id)),
        parameters=FrozenObject.of({"schema": RUN_SCHEMA, "replicate": replicate}),
    )
    store.publish(run)
    return experiment, run


def load_training_input(
    store: ArtifactStore, input_id: str, runtime: Producer
) -> tuple[Manifest, TrainingConfig, LoadedFeatures]:
    training = store.get_manifest(input_id)
    info = training.parameters.value()
    if (
        training.kind != "training_input"
        or info.get("schema") != TRAINING_SCHEMA
        or info.get("entrypoint") != ENTRYPOINT
        or training.producer != runtime
    ):
        raise BoundaryError("worker", "source_lock_or_entrypoint_mismatch")
    if sorted(p.role for p in training.parents) not in [
        ["dataset", "feature_set", "model_view"],
        ["dataset", "feature_set", "model_view", "protocol"],
    ]:
        raise BoundaryError("worker", "training_parent_inventory_mismatch")
    config = TrainingConfig.decode(info.get("config"))
    features = load_features(store, training.parent("feature_set"))
    if (
        features.view.artifact_id != training.parent("model_view")
        or features.view.parent("dataset") != training.parent("dataset")
        or features.manifest.parameters.value()["qwen"] != info.get("qwen")
        or features.view.parameters.value()["serializer"] != info.get("serializer")
        or features.manifest.parameters.value()["scope"] != info.get("scope")
    ):
        raise BoundaryError("worker", "input_lineage_mismatch")
    protocol_id = next((p.artifact_id for p in training.parents if p.role == "protocol"), None)
    _research_admission(store, features, config, protocol_id)
    return training, config, features
