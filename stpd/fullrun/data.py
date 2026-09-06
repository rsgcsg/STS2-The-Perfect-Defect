"""Full-Run admission, semantic-component/whole-run splits and canonical datasets."""

from __future__ import annotations

import hashlib
import io
import tempfile
from collections import defaultdict
from dataclasses import dataclass

from ..artifact_contracts import Manifest, Parent, Producer
from ..canonical import canonical_json, semantic_hash
from ..json_boundary import BoundaryError, FrozenObject, decode_json, json_bytes, unsigned
from ..storage.store import ArtifactStore
from .contracts import ResearchTransitionV1, SourceAdapter, SourceProjection
from .representation import decision_fingerprint

DATASET_SCHEMA = "stpd/fullrun-dataset-v1"


@dataclass(frozen=True)
class AdmittedDataset:
    records: tuple[ResearchTransitionV1, ...]
    splits: FrozenObject
    seed: int
    scope: str
    exact_duplicates: int = 0

    @property
    def logical_id(self) -> str:
        return semantic_hash({"schema": DATASET_SCHEMA, "scope": self.scope, "seed": self.seed,
                              "records": [r.to_dict() for r in self.records],
                              "splits": self.splits.value()})


def split_whole_runs(records: tuple[ResearchTransitionV1, ...], seed: int) -> FrozenObject:
    """Keep entire runs and repeated semantic decision components in a single partition."""
    unsigned(seed, "split.seed")
    parent = {record.run_id: record.run_id for record in records}

    def root(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    first: dict[str, str] = {}
    for record in records:
        fingerprint = decision_fingerprint(record)
        previous = first.setdefault(fingerprint, record.run_id)
        left, right = root(previous), root(record.run_id)
        if left != right:
            parent[max(left, right)] = min(left, right)
    groups: dict[str, list[str]] = defaultdict(list)
    for run_id in sorted(parent):
        groups[root(run_id)].append(run_id)
    components = sorted(groups.values(), key=lambda group: semantic_hash([seed, group]))
    if len(components) < 3:
        raise BoundaryError("split", "insufficient_independent_run_components",
                            "collect at least three independent run components")
    test_count = max(1, len(components) // 10)
    dev_count = max(1, len(components) // 10)
    assignments: dict[str, str] = {}
    for index, component in enumerate(components):
        partition = "test" if index < test_count else (
            "dev" if index < test_count + dev_count else "train")
        assignments.update({run_id: partition for run_id in component})
    return FrozenObject.of(assignments)


def admit(projections: tuple[SourceProjection, ...], *, seed: int = 0) -> AdmittedDataset:
    if not projections or any(not isinstance(p, SourceProjection) for p in projections):
        raise BoundaryError("admission", "no_verified_source_projection")
    scopes = {projection.scope for projection in projections}
    if len(scopes) != 1:
        raise BoundaryError("admission", "mixed_engineering_and_qualified_sources")
    unique: dict[str, ResearchTransitionV1] = {}
    positions: dict[tuple[str, int], str] = {}
    duplicates = 0
    for projection in projections:
        proof_map = projection.run_proofs.value()
        projected_runs = {record.run_id for record in projection.transitions}
        if set(proof_map) != projected_runs:
            raise BoundaryError("admission", "run_proof_inventory_mismatch")
        for record in projection.transitions:
            if not record.rank_eligible:
                raise BoundaryError("admission", "incomplete_or_uncommitted_decision")
            decision_fingerprint(record)
            previous = unique.get(record.transition_id)
            if previous is not None:
                if previous.to_dict() != record.to_dict():
                    raise BoundaryError("admission", "transition_identity_collision")
                duplicates += 1
                continue
            position = (record.run_id, record.step_index)
            if position in positions:
                raise BoundaryError("admission", "run_step_collision")
            positions[position] = record.transition_id
            unique[record.transition_id] = record
    records = tuple(sorted(unique.values(), key=lambda r: (r.run_id, r.step_index, r.transition_id)))
    if not records:
        raise BoundaryError("admission", "empty_dataset")
    for run_id in {record.run_id for record in records}:
        run = [record for record in records if record.run_id == run_id]
        if [record.step_index for record in run] != list(range(len(run))):
            raise BoundaryError("admission", "missing_run_step")
        if any(record.terminal for record in run[:-1]):
            raise BoundaryError("admission", "decision_after_terminal")
        for projection in projections:
            proof = projection.run_proofs.value().get(run_id)
            if proof is not None and proof.get("record_count") != len(run):
                raise BoundaryError("admission", "source_disposition_count_mismatch")
    return AdmittedDataset(records, split_whole_runs(records, seed), seed, scopes.pop(), duplicates)


def publish_source(store: ArtifactStore, raw: bytes, adapter: SourceAdapter,
                   producer: Producer) -> tuple[Manifest, SourceProjection]:
    projection = adapter.project(raw)
    if hashlib.sha256(raw).hexdigest() != projection.source_sha256:
        raise BoundaryError("source", "adapter_source_hash_mismatch")
    payload = store.put_payload("source", io.BytesIO(raw), "application/json")
    manifest = Manifest("evidence", producer, payloads=(payload,), parameters=FrozenObject.of({
        "schema": "stpd/source-projection-v1", "adapter": projection.adapter_id,
        "scope": projection.scope, "source_sha256": projection.source_sha256,
        "run_proofs": projection.run_proofs.value(),
    }))
    store.publish(manifest)
    return manifest, projection


def _projections_from_manifests(records: tuple[ResearchTransitionV1, ...],
                               sources: tuple[Manifest, ...]) -> tuple[SourceProjection, ...]:
    by_source = {source.payload("source").sha256: source for source in sources}
    if not sources or len(by_source) != len(sources):
        raise BoundaryError("dataset", "source_inventory_mismatch")
    if set(by_source) != {r.provenance.bundle_sha256 for r in records}:
        raise BoundaryError("dataset", "source_inventory_mismatch")
    projections = []
    for source_hash, source in by_source.items():
        info = source.parameters.value()
        if (source.kind != "evidence" or info.get("schema") != "stpd/source-projection-v1"
                or info.get("source_sha256") != source_hash):
            raise BoundaryError("dataset", "invalid_source_manifest")
        projections.append(SourceProjection(
            info["adapter"], source_hash, info["scope"], FrozenObject.of(info["run_proofs"]),
            tuple(record for record in records if record.provenance.bundle_sha256 == source_hash),
        ))
    return tuple(projections)


def publish_dataset(store: ArtifactStore, dataset: AdmittedDataset,
                    sources: tuple[Manifest, ...], producer: Producer) -> Manifest:
    import pyarrow as pa
    import pyarrow.parquet as pq

    verified = admit(_projections_from_manifests(dataset.records, sources), seed=dataset.seed)
    if dataset.logical_id != verified.logical_id or dataset.scope != verified.scope:
        raise BoundaryError("dataset", "unadmitted_publication")
    rows = [{"transition_id": record.transition_id, "run_id": record.run_id,
             "step_index": record.step_index, "surface": record.surface, "family": record.family,
             "split": dataset.splits.value()[record.run_id],
             "record_json": canonical_json(record.to_dict())} for record in dataset.records]
    schema = pa.schema([("transition_id", pa.string()), ("run_id", pa.string()),
                        ("step_index", pa.int64()), ("surface", pa.string()),
                        ("family", pa.string()), ("split", pa.string()), ("record_json", pa.string())])
    with tempfile.TemporaryFile("w+b") as handle:
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), handle,
                       compression="zstd", version="2.6", use_dictionary=True)
        handle.seek(0)
        records_payload = store.put_payload("records", handle, "application/vnd.apache.parquet")
    splits_payload = store.put_payload("splits", io.BytesIO(json_bytes(dataset.splits.value())),
                                       "application/json")
    manifest = Manifest("dataset", producer,
                        parents=tuple(Parent("evidence", source.artifact_id) for source in sources),
                        payloads=(records_payload, splits_payload), parameters=FrozenObject.of({
                            "schema": DATASET_SCHEMA, "logical_id": dataset.logical_id,
                            "scope": dataset.scope, "seed": dataset.seed,
                            "records": len(dataset.records), "runs": len(dataset.splits.value()),
                            "exact_duplicates": dataset.exact_duplicates,
                            "whole_run_and_semantic_component_isolation": True,
                        }))
    store.publish(manifest)
    return manifest


def load_dataset(store: ArtifactStore, artifact_id: str) -> tuple[Manifest, AdmittedDataset]:
    import pyarrow.parquet as pq

    manifest = store.get_manifest(artifact_id)
    parameters = manifest.parameters.value()
    if manifest.kind != "dataset" or parameters.get("schema") != DATASET_SCHEMA:
        raise BoundaryError("dataset", "unsupported_dataset_contract")
    if {p.role for p in manifest.payloads} != {"records", "splits"}:
        raise BoundaryError("dataset", "payload_inventory_mismatch")
    if manifest.payload("splits").size > 16 * 1024 * 1024:
        raise BoundaryError("dataset", "split_manifest_too_large")
    splits_raw = b"".join(store.read_payload(manifest.payload("splits")))
    splits = decode_json(splits_raw)
    if not isinstance(splits, dict) or splits_raw != json_bytes(splits):
        raise BoundaryError("dataset", "invalid_split_manifest")
    records: list[ResearchTransitionV1] = []
    with tempfile.TemporaryFile("w+b") as handle:
        for chunk in store.read_payload(manifest.payload("records")):
            handle.write(chunk)
        handle.seek(0)
        parquet = pq.ParquetFile(handle)
        if set(parquet.schema_arrow.names) != {
            "transition_id", "run_id", "step_index", "surface", "family", "split", "record_json",
        }:
            raise BoundaryError("dataset", "parquet_columns_mismatch")
        for batch in parquet.iter_batches(batch_size=1024):
            for row in batch.to_pylist():
                record = ResearchTransitionV1.decode(decode_json(row["record_json"]))
                expected = {"transition_id": record.transition_id, "run_id": record.run_id,
                            "step_index": record.step_index, "surface": record.surface,
                            "family": record.family, "split": splits.get(record.run_id),
                            "record_json": canonical_json(record.to_dict())}
                if row != expected:
                    raise BoundaryError("dataset", "column_record_alignment_mismatch")
                records.append(record)
    sources = tuple(store.get_manifest(parent.artifact_id) for parent in manifest.parents)
    if any(p.role != "evidence" for p in manifest.parents):
        raise BoundaryError("dataset", "source_inventory_mismatch")
    admitted = admit(_projections_from_manifests(tuple(records), sources),
                     seed=unsigned(parameters.get("seed"), "dataset.seed"))
    if (len(admitted.records) != len(records) or admitted.splits.value() != splits
            or admitted.logical_id != parameters.get("logical_id")
            or len(records) != parameters.get("records")
            or len(splits) != parameters.get("runs") or admitted.scope != parameters.get("scope")):
        raise BoundaryError("dataset", "admission_or_identity_mismatch")
    return manifest, admitted
