"""Arrow/Parquet storage for frozen ResearchTransition v0 records."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ..canonical import canonical_json, semantic_hash, to_json_value

TRANSITION_ARROW_SCHEMA = pa.schema(
    [
        pa.field("transition_id", pa.string(), nullable=False),
        pa.field("episode_id", pa.string(), nullable=False),
        pa.field("step_index", pa.int32(), nullable=False),
        pa.field("seed", pa.string(), nullable=False),
        pa.field("decision_mode", pa.string(), nullable=False),
        pa.field("surface", pa.string(), nullable=False),
        pa.field("input_profile", pa.string(), nullable=False),
        pa.field("environment_json", pa.large_string(), nullable=False),
        pa.field("policy_json", pa.large_string(), nullable=False),
        pa.field("eligibility_json", pa.large_string(), nullable=False),
        pa.field("state_json", pa.large_string(), nullable=False),
        pa.field("legal_actions_json", pa.large_string(), nullable=False),
        pa.field("chosen_action_json", pa.large_string(), nullable=False),
        pa.field("successor_json", pa.large_string(), nullable=True),
        pa.field("terminal", pa.bool_(), nullable=False),
        pa.field("scope_exit", pa.bool_(), nullable=False),
        pa.field("outcome_json", pa.large_string(), nullable=True),
        pa.field("raw_ref", pa.string(), nullable=False),
        pa.field("record_hash", pa.string(), nullable=False),
    ],
    metadata={
        b"stpd.schema": b"stpd/research-transition-v0",
        b"stpd.encoding": b"canonical-json-columns-v0",
    },
)


_JSON_COLUMNS = {
    "environment": "environment_json",
    "policy": "policy_json",
    "eligibility": "eligibility_json",
    "state": "state_json",
    "legal_actions": "legal_actions_json",
    "chosen_action": "chosen_action_json",
    "successor": "successor_json",
    "outcome": "outcome_json",
}


def _row(record: Mapping[str, Any]) -> dict[str, Any]:
    canonical = to_json_value(record)
    if not isinstance(canonical, dict):
        raise TypeError("transition record must be an object")
    row = {
        "transition_id": canonical["transition_id"],
        "episode_id": canonical["episode_id"],
        "step_index": canonical["step_index"],
        "seed": canonical["seed"],
        "decision_mode": canonical["decision_mode"],
        "surface": canonical["surface"],
        "input_profile": canonical["input_profile"],
        "terminal": canonical["terminal"],
        "scope_exit": canonical["scope_exit"],
        "raw_ref": canonical["raw_ref"],
        "record_hash": semantic_hash(canonical),
    }
    for source, destination in _JSON_COLUMNS.items():
        value = canonical[source]
        row[destination] = None if value is None else canonical_json(value)
    return row


def write_transition_parquet(
    records: Iterable[Mapping[str, Any]], path: str | Path
) -> tuple[int, str]:
    """Write canonical transitions and return `(row_count, semantic_dataset_hash)`."""

    rows = [_row(record) for record in records]
    if not rows:
        raise ValueError("cannot write an empty transition dataset")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=TRANSITION_ARROW_SCHEMA)
    pq.write_table(
        table,
        destination,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="2.0",
    )
    dataset_hash = semantic_hash([row["record_hash"] for row in rows])
    return len(rows), dataset_hash


def read_transition_parquet(path: str | Path) -> list[dict[str, Any]]:
    """Read Parquet into the frozen JSON contract and verify stored record hashes."""

    table = pq.read_table(Path(path), schema=TRANSITION_ARROW_SCHEMA)
    records: list[dict[str, Any]] = []
    for row in table.to_pylist():
        record: dict[str, Any] = {
            "schema": "stpd/research-transition-v0",
            "transition_id": row["transition_id"],
            "episode_id": row["episode_id"],
            "step_index": row["step_index"],
            "seed": row["seed"],
            "decision_mode": row["decision_mode"],
            "surface": row["surface"],
            "input_profile": row["input_profile"],
            "terminal": row["terminal"],
            "scope_exit": row["scope_exit"],
            "raw_ref": row["raw_ref"],
        }
        for source, encoded in _JSON_COLUMNS.items():
            value = row[encoded]
            record[source] = None if value is None else json.loads(value)
        if semantic_hash(record) != row["record_hash"]:
            raise ValueError(f"record hash mismatch for {record['transition_id']}")
        records.append(record)
    return records
