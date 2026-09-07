"""Read-only profiling for the canonical STPD data lifecycle.

The profiler measures the physical representation without changing the frozen
``ResearchTransition`` contract. Candidate layouts are written only to a
temporary directory and must reconstruct every canonical record exactly.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ..canonical import canonical_json, semantic_hash
from ..contracts import ContractError
from .parquet import TRANSITION_ARROW_SCHEMA, read_transition_parquet


class LifecycleProfileError(ContractError):
    """Raised when a dataset cannot be profiled without weakening identity checks."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LifecycleProfileError(f"{name} must be an object")
    return value


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise LifecycleProfileError(f"{name} must be an array")
    return value


def _manifest_dataset(directory: Path) -> tuple[dict[str, Any], Path]:
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LifecycleProfileError("cannot read canonical dataset manifest") from error
    manifest = dict(_object(manifest, "manifest"))
    if manifest.get("schema") != "stpd/data-manifest-v0":
        raise LifecycleProfileError("unsupported canonical dataset manifest schema")
    files = _sequence(manifest.get("files"), "manifest.files")
    matches = [dict(_object(item, "manifest.files[]")) for item in files]
    matches = [item for item in matches if item.get("path") == "transitions.parquet"]
    if len(matches) != 1:
        raise LifecycleProfileError("manifest must bind exactly one transitions.parquet")
    parquet_path = directory / "transitions.parquet"
    if not parquet_path.is_file():
        raise LifecycleProfileError("manifest-bound transitions.parquet is missing")
    file_entry = matches[0]
    if file_entry.get("sha256") != _sha256(parquet_path):
        raise LifecycleProfileError("manifest-bound Parquet checksum mismatch")
    if file_entry.get("bytes") != parquet_path.stat().st_size:
        raise LifecycleProfileError("manifest-bound Parquet size mismatch")
    return manifest, parquet_path


def _timed_verified_read(path: Path, repeats: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    durations: list[int] = []
    records: list[dict[str, Any]] = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        current = read_transition_parquet(path)
        durations.append((time.perf_counter_ns() - started) // 1_000)
        if records and current != records:
            raise LifecycleProfileError("repeated verified reads produced different records")
        records = current
    ordered = sorted(durations)
    return records, {
        "repeats": repeats,
        "min_us": ordered[0],
        "median_us": ordered[len(ordered) // 2],
        "max_us": ordered[-1],
    }


def _logical_column_profile(path: Path) -> tuple[dict[str, Any], int]:
    table = pq.read_table(path, schema=TRANSITION_ARROW_SCHEMA)
    columns: dict[str, Any] = {}
    total = 0
    for name in table.column_names:
        values = table.column(name).to_pylist()
        logical_bytes = sum(
            len(value.encode("utf-8"))
            if isinstance(value, str)
            else 1
            if isinstance(value, bool)
            else 8
            for value in values
            if value is not None
        )
        total += logical_bytes
        columns[name] = {
            "logical_bytes": logical_bytes,
            "null_count": sum(value is None for value in values),
            "unique_values": len({canonical_json(value) for value in values}),
        }
    return columns, total


def _semantic_reuse(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    state_refs: Counter[str] = Counter()
    catalog_refs: Counter[str] = Counter()
    episode_envelopes: Counter[str] = Counter()
    chosen_membership_failures = 0
    chosen_duplicate_bytes = 0
    by_episode: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        state_refs[semantic_hash(record["state"])] += 1
        if record["successor"] is not None:
            state_refs[semantic_hash(record["successor"])] += 1
        catalog = list(_sequence(record["legal_actions"], "record.legal_actions"))
        catalog_refs[semantic_hash(catalog)] += 1
        chosen = canonical_json(record["chosen_action"])
        chosen_duplicate_bytes += len(chosen.encode("utf-8"))
        if chosen not in {canonical_json(action) for action in catalog}:
            chosen_membership_failures += 1
        episode_envelopes[
            semantic_hash(
                {
                    "environment": record["environment"],
                    "policy": record["policy"],
                    "seed": record["seed"],
                    "input_profile": record["input_profile"],
                }
            )
        ] += 1
        by_episode.setdefault(str(record["episode_id"]), []).append(record)

    links = 0
    equal_links = 0
    for episode in by_episode.values():
        ordered = sorted(episode, key=lambda item: int(item["step_index"]))
        for current, following in zip(ordered, ordered[1:], strict=False):
            if current["successor"] is None:
                continue
            links += 1
            if semantic_hash(current["successor"]) == semantic_hash(following["state"]):
                equal_links += 1
    return {
        "episodes": len(by_episode),
        "state_references": sum(state_refs.values()),
        "unique_states": len(state_refs),
        "state_reuse_ratio": round(sum(state_refs.values()) / max(1, len(state_refs)), 6),
        "catalog_references": sum(catalog_refs.values()),
        "unique_ordered_catalogs": len(catalog_refs),
        "catalog_reuse_ratio": round(sum(catalog_refs.values()) / max(1, len(catalog_refs)), 6),
        "successor_next_state_links": links,
        "successor_equals_next_state": equal_links,
        "successor_next_state_share": round(equal_links / max(1, links), 6),
        "episode_envelope_variants": len(episode_envelopes),
        "chosen_action_duplicate_bytes": chosen_duplicate_bytes,
        "chosen_action_membership_failures": chosen_membership_failures,
    }


def _write_probe_table(path: Path, rows: list[dict[str, Any]], *, dictionary: bool) -> None:
    pq.write_table(
        pa.Table.from_pylist(rows),
        path,
        compression="zstd",
        use_dictionary=dictionary,
        write_statistics=True,
        data_page_version="2.0",
    )


def _object_reference_probe(
    records: Sequence[Mapping[str, Any]], directory: Path
) -> tuple[int, list[dict[str, Any]]]:
    objects: dict[str, dict[str, Any]] = {}
    steps: list[dict[str, Any]] = []

    def reference(kind: str, value: Any) -> str | None:
        if value is None:
            return None
        encoded = canonical_json(value)
        digest = semantic_hash({"kind": kind, "value": value})
        objects.setdefault(digest, {"object_ref": digest, "kind": kind, "json": encoded})
        return digest

    for record in records:
        catalog = list(_sequence(record["legal_actions"], "record.legal_actions"))
        chosen = canonical_json(record["chosen_action"])
        try:
            chosen_index = [canonical_json(action) for action in catalog].index(chosen)
        except ValueError as error:
            raise LifecycleProfileError(
                "chosen action is absent from its ordered catalog"
            ) from error
        steps.append(
            {
                "transition_id": record["transition_id"],
                "episode_id": record["episode_id"],
                "step_index": record["step_index"],
                "seed": record["seed"],
                "decision_mode": record["decision_mode"],
                "surface": record["surface"],
                "input_profile": record["input_profile"],
                "environment_ref": reference("environment", record["environment"]),
                "policy_ref": reference("policy", record["policy"]),
                "eligibility_ref": reference("eligibility", record["eligibility"]),
                "state_ref": reference("state", record["state"]),
                "catalog_ref": reference("catalog", catalog),
                "chosen_index": chosen_index,
                "successor_ref": reference("state", record["successor"]),
                "terminal": record["terminal"],
                "scope_exit": record["scope_exit"],
                "outcome_ref": reference("outcome", record["outcome"]),
                "raw_ref": record["raw_ref"],
                "record_hash": semantic_hash(record),
            }
        )
    object_rows = [objects[key] for key in sorted(objects)]
    _write_probe_table(directory / "objects.parquet", object_rows, dictionary=False)
    _write_probe_table(directory / "steps.parquet", steps, dictionary=False)

    materialized_objects = {
        row["object_ref"]: json.loads(row["json"])
        for row in pq.read_table(directory / "objects.parquet").to_pylist()
    }
    reconstructed: list[dict[str, Any]] = []
    for row in pq.read_table(directory / "steps.parquet").to_pylist():
        catalog = materialized_objects[row["catalog_ref"]]
        record = {
            "schema": "stpd/research-transition-v0",
            "transition_id": row["transition_id"],
            "episode_id": row["episode_id"],
            "step_index": row["step_index"],
            "seed": row["seed"],
            "decision_mode": row["decision_mode"],
            "surface": row["surface"],
            "input_profile": row["input_profile"],
            "environment": materialized_objects[row["environment_ref"]],
            "policy": materialized_objects[row["policy_ref"]],
            "eligibility": materialized_objects[row["eligibility_ref"]],
            "state": materialized_objects[row["state_ref"]],
            "legal_actions": catalog,
            "chosen_action": catalog[row["chosen_index"]],
            "successor": (
                None
                if row["successor_ref"] is None
                else materialized_objects[row["successor_ref"]]
            ),
            "terminal": row["terminal"],
            "scope_exit": row["scope_exit"],
            "outcome": (
                None if row["outcome_ref"] is None else materialized_objects[row["outcome_ref"]]
            ),
            "raw_ref": row["raw_ref"],
        }
        if semantic_hash(record) != row["record_hash"]:
            raise LifecycleProfileError("object-reference probe record hash mismatch")
        reconstructed.append(record)
    return sum(path.stat().st_size for path in directory.iterdir()), reconstructed


def _layout_probes(records: Sequence[Mapping[str, Any]], current_bytes: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="stpd-layout-profile-") as temporary:
        root = Path(temporary)
        current_rows = [
            {
                "payload_json": canonical_json(record),
                "record_hash": semantic_hash(record),
            }
            for record in records
        ]
        monolithic = root / "monolithic.parquet"
        _write_probe_table(monolithic, current_rows, dictionary=False)

        object_root = root / "object_refs"
        object_root.mkdir()
        object_bytes, reconstructed = _object_reference_probe(records, object_root)
        if reconstructed != list(records):
            raise LifecycleProfileError("object-reference probe failed exact reconstruction")

        dictionary = root / "dictionary.parquet"
        # Recreate the current Arrow rows through the public schema to isolate the
        # physical effect of dictionary encoding from semantic normalization.
        encoded_rows = []
        for record in records:
            encoded_rows.append(
                {
                    "transition_id": record["transition_id"],
                    "episode_id": record["episode_id"],
                    "step_index": record["step_index"],
                    "seed": record["seed"],
                    "decision_mode": record["decision_mode"],
                    "surface": record["surface"],
                    "input_profile": record["input_profile"],
                    "environment_json": canonical_json(record["environment"]),
                    "policy_json": canonical_json(record["policy"]),
                    "eligibility_json": canonical_json(record["eligibility"]),
                    "state_json": canonical_json(record["state"]),
                    "legal_actions_json": canonical_json(record["legal_actions"]),
                    "chosen_action_json": canonical_json(record["chosen_action"]),
                    "successor_json": (
                        None
                        if record["successor"] is None
                        else canonical_json(record["successor"])
                    ),
                    "terminal": record["terminal"],
                    "scope_exit": record["scope_exit"],
                    "outcome_json": (
                        None if record["outcome"] is None else canonical_json(record["outcome"])
                    ),
                    "raw_ref": record["raw_ref"],
                    "record_hash": semantic_hash(record),
                }
            )
        pq.write_table(
            pa.Table.from_pylist(encoded_rows, schema=TRANSITION_ARROW_SCHEMA),
            dictionary,
            compression="zstd",
            use_dictionary=True,
            write_statistics=True,
            data_page_version="2.0",
        )
        candidates = {
            "current_canonical": current_bytes,
            "monolithic_record_json": monolithic.stat().st_size,
            "current_columns_dictionary": dictionary.stat().st_size,
            "content_addressed_objects": object_bytes,
        }
        return {
            "bytes": candidates,
            "relative_to_current": {
                name: round(size / current_bytes, 6) for name, size in candidates.items()
            },
            "exact_reconstruction": {"content_addressed_objects": True},
            "production_migration_authorized": False,
        }


def profile_canonical_dataset(
    dataset_directory: str | Path, *, read_repeats: int = 3, probe_layouts: bool = True
) -> dict[str, Any]:
    """Verify and profile one immutable canonical dataset directory."""

    if read_repeats <= 0:
        raise ValueError("read_repeats must be positive")
    directory = Path(dataset_directory).expanduser().resolve()
    manifest, parquet_path = _manifest_dataset(directory)
    records, verified_read = _timed_verified_read(parquet_path, read_repeats)
    if len(records) != manifest.get("row_count"):
        raise LifecycleProfileError("manifest row_count differs from verified Parquet")
    semantic_dataset_hash = semantic_hash([semantic_hash(record) for record in records])
    file_entry = next(
        item for item in manifest["files"] if item.get("path") == "transitions.parquet"
    )
    if file_entry.get("semantic_hash") != semantic_dataset_hash:
        raise LifecycleProfileError("manifest semantic hash differs from verified records")
    columns, logical_bytes = _logical_column_profile(parquet_path)
    physical_bytes = parquet_path.stat().st_size
    report: dict[str, Any] = {
        "schema": "stpd/data-lifecycle-profile-v1",
        "dataset": {
            "directory": str(directory),
            "manifest_id": manifest.get("manifest_id"),
            "manifest_sha256": _sha256(directory / "manifest.json"),
            "parquet_sha256": _sha256(parquet_path),
            "semantic_dataset_hash": semantic_dataset_hash,
            "rows": len(records),
        },
        "current_layout": {
            "encoding": "canonical-json-columns-v0",
            "physical_bytes": physical_bytes,
            "logical_column_bytes": logical_bytes,
            "physical_to_logical_ratio": round(physical_bytes / max(1, logical_bytes), 6),
            "columns": columns,
            "verified_materialization": verified_read,
        },
        "semantic_reuse": _semantic_reuse(records),
        "claims": [
            "The manifest, physical checksum, semantic dataset hash, and record hashes "
            "were verified.",
            "Layout probes are temporary engineering measurements, not canonical datasets.",
        ],
        "non_claims": [
            "This profile does not authorize training or change corpus identity.",
            "A small local corpus does not establish full-corpus or training-host performance.",
        ],
    }
    if probe_layouts:
        report["layout_probes"] = _layout_probes(records, physical_bytes)
    return report
