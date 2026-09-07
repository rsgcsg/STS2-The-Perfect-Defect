"""Immutable Gold collection, exact Dataset binding and sealed-test access boundaries."""

from __future__ import annotations

import io
from typing import Any

from ..artifact_contracts import Manifest, Parent, Producer
from ..json_boundary import (
    BoundaryError,
    FrozenObject,
    array,
    decode_json,
    json_bytes,
    object_fields,
)
from ..storage.store import ArtifactStore
from .data import load_dataset
from .gold import (
    GOLD_ANNOTATION_SCHEMA,
    GOLD_LABEL_MANIFEST_SCHEMA,
    GOLD_TASK_MANIFEST_SCHEMA,
    GoldAnnotation,
    GoldSplit,
    GoldTask,
    audit_gold,
    sample_gold_tasks,
)
from .representation import FullRunSerializer


def decode_annotation(value: object) -> GoldAnnotation:
    fields = {
        "schema",
        "annotation_id",
        "task_id",
        "annotator_id",
        "gold_split",
        "candidate_action_keys",
        "candidate_display_order",
        "disposition",
        "acceptable_actions",
        "best_action",
        "confidence",
        "origin",
        "state_hash",
    }
    obj = object_fields(value, fields, "gold.annotation")
    if obj["schema"] != GOLD_ANNOTATION_SCHEMA:
        raise BoundaryError("gold.annotation", "unsupported_schema")
    result = GoldAnnotation(
        obj["annotation_id"],
        obj["task_id"],
        obj["annotator_id"],
        obj["gold_split"],
        tuple(array(obj["candidate_action_keys"], "gold.catalog")),
        tuple(array(obj["candidate_display_order"], "gold.display")),
        obj["disposition"],
        tuple(array(obj["acceptable_actions"], "gold.acceptable")),
        obj["best_action"],
        obj["confidence"],
        obj["origin"],
        obj["schema"],
        obj["state_hash"],
    )
    result.validate(allow_synthetic=True)
    return result


def _json_payload(store: ArtifactStore, manifest: Manifest, role: str) -> Any:
    payload = manifest.payload(role)
    if payload.size > 64 * 1024 * 1024:
        raise BoundaryError("gold", "payload_size_limit")
    raw = b"".join(store.read_payload(payload))
    value = decode_json(raw)
    if raw != json_bytes(value):
        raise BoundaryError("gold", "noncanonical_payload")
    return value


def publish_tasks(
    store: ArtifactStore,
    dataset_id: str,
    producer: Producer,
    *,
    gold_split: GoldSplit,
    count: int,
    seed: int = 0,
    profile: str = "standard",
) -> Manifest:
    _, dataset = load_dataset(store, dataset_id)
    tasks = sample_gold_tasks(
        dataset,
        gold_split=gold_split,
        count=count,
        seed=seed,
        serializer=FullRunSerializer(profile),
        source_dataset_id=dataset_id,
    )
    payload = store.put_payload("tasks", io.BytesIO(json_bytes([t.to_dict() for t in tasks])))
    manifest = Manifest(
        "gold_tasks",
        producer,
        (Parent("dataset", dataset_id),),
        (payload,),
        FrozenObject.of(
            {
                "schema": GOLD_TASK_MANIFEST_SCHEMA,
                "gold_split": gold_split,
                "count": count,
                "seed": seed,
                "profile": profile,
                "scope": dataset.scope,
            }
        ),
    )
    store.publish(manifest)
    return manifest


def load_tasks(store: ArtifactStore, task_id: str) -> tuple[Manifest, tuple[GoldTask, ...]]:
    manifest = store.get_manifest(task_id)
    info = manifest.parameters.value()
    if (
        manifest.kind != "gold_tasks"
        or info.get("schema") != GOLD_TASK_MANIFEST_SCHEMA
        or {p.role for p in manifest.parents} != {"dataset"}
        or {p.role for p in manifest.payloads} != {"tasks"}
    ):
        raise BoundaryError("gold", "task_manifest_mismatch")
    _, dataset = load_dataset(store, manifest.parent("dataset"))
    expected = sample_gold_tasks(
        dataset,
        gold_split=info["gold_split"],
        count=info.get("count"),
        seed=info["seed"],
        serializer=FullRunSerializer(info["profile"]),
        source_dataset_id=manifest.parent("dataset"),
    )
    tasks = tuple(
        GoldTask.decode(v) for v in array(_json_payload(store, manifest, "tasks"), "gold.tasks")
    )
    if tasks != expected or info.get("scope") != dataset.scope:
        raise BoundaryError("gold", "source_task_mismatch")
    return manifest, tasks


def publish_labels(
    store: ArtifactStore,
    task_id: str,
    annotations: tuple[GoldAnnotation, ...],
    producer: Producer,
    *,
    allow_synthetic: bool = False,
) -> Manifest:
    task_manifest, tasks = load_tasks(store, task_id)
    audit_gold(
        tasks,
        annotations,
        sealed=tasks[0].gold_split == "gold_test",
        allow_synthetic=allow_synthetic,
    )
    ordered = sorted(annotations, key=lambda value: (value.task_id, value.annotator_id))
    payload = store.put_payload(
        "labels",
        io.BytesIO(json_bytes([a.to_dict(allow_synthetic=allow_synthetic) for a in ordered])),
    )
    manifest = Manifest(
        "gold_labels",
        producer,
        (Parent("gold_tasks", task_id),),
        (payload,),
        FrozenObject.of(
            {
                "schema": GOLD_LABEL_MANIFEST_SCHEMA,
                "gold_split": tasks[0].gold_split,
                "scope": task_manifest.parameters.value()["scope"],
                "origin": "human_attested" if not allow_synthetic else "synthetic_engineering",
                "sealed": tasks[0].gold_split == "gold_test",
            }
        ),
    )
    store.publish(manifest)
    return manifest


def gold_report(
    store: ArtifactStore, label_id: str, *, mode: str = "coverage", protocol_id: str | None = None
) -> dict[str, Any]:
    manifest = store.get_manifest(label_id)
    info = manifest.parameters.value()
    if (
        manifest.kind != "gold_labels"
        or info.get("schema") != GOLD_LABEL_MANIFEST_SCHEMA
        or {p.role for p in manifest.parents} != {"gold_tasks"}
        or {p.role for p in manifest.payloads} != {"labels"}
    ):
        raise BoundaryError("gold", "label_manifest_mismatch")
    if mode not in {"coverage", "tuning", "evaluation"}:
        raise BoundaryError("gold", "gold_training_forbidden")
    task_manifest, tasks = load_tasks(store, manifest.parent("gold_tasks"))
    sealed = tasks[0].gold_split == "gold_test"
    if info.get("sealed") != sealed or info["gold_split"] != tasks[0].gold_split:
        raise BoundaryError("gold", "label_split_mismatch")
    if sealed and mode != "coverage":
        if mode == "tuning" or protocol_id is None:
            raise BoundaryError("gold", "sealed_test_protocol_required")
        protocol = store.get_manifest(protocol_id)
        rule = protocol.parameters.value()
        if (
            protocol.kind != "protocol"
            or rule.get("status") != "frozen"
            or rule.get("schema") != "stpd/fullrun-gold-evaluation-protocol-v1"
            or rule.get("gold_labels_id") != label_id
            or rule.get("model_id") is None
        ):
            raise BoundaryError("gold", "sealed_test_protocol_mismatch")
        if store.get_manifest(rule["model_id"]).kind != "model":
            raise BoundaryError("gold", "frozen_model_required")
    labels = tuple(
        decode_annotation(v) for v in array(_json_payload(store, manifest, "labels"), "gold.labels")
    )
    synthetic = info.get("origin") == "synthetic_engineering"
    report = audit_gold(tasks, labels, sealed=sealed, allow_synthetic=synthetic).to_dict()
    if info.get("scope") != task_manifest.parameters.value()["scope"]:
        raise BoundaryError("gold", "label_scope_mismatch")
    if sealed and mode == "coverage":
        report = {
            key: report[key]
            for key in (
                "schema",
                "gold_split",
                "sealed",
                "task_count",
                "annotation_count",
                "covered_task_count",
                "coverage",
            )
        }
    return {**report, "origin": info["origin"], "scientific_verdict": "not_claimed"}
