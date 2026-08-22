"""Checksummed provenance manifest for canonical STPD datasets."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..canonical import semantic_hash, to_json_value
from ..contracts import ContractError


@dataclass(frozen=True)
class DataSource:
    source_id: str
    kind: str
    source_revision: str
    license_spdx: str
    provenance_uri: str

    def validate(self) -> None:
        for name, value in (
            ("source_id", self.source_id),
            ("kind", self.kind),
            ("source_revision", self.source_revision),
            ("license_spdx", self.license_spdx),
            ("provenance_uri", self.provenance_uri),
        ):
            if not value.strip():
                raise ContractError(f"data source {name} must be non-empty")
        if self.license_spdx.lower() in {"unknown", "unverified", "none"}:
            raise ContractError("unknown or unverified source license is not admissible")


@dataclass(frozen=True)
class DataFile:
    path: str
    sha256: str
    bytes: int
    rows: int
    semantic_hash: str

    @classmethod
    def from_path(cls, path: str | Path, *, rows: int, semantic_hash_: str) -> DataFile:
        source = Path(path)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        return cls(source.name, digest, source.stat().st_size, rows, semantic_hash_)


@dataclass(frozen=True)
class DataManifest:
    manifest_id: str
    created_at: str
    source_revision: str
    contract_schema: str
    sources: tuple[DataSource, ...]
    files: tuple[DataFile, ...]
    row_count: int
    split: dict[str, Any]
    deduplication: dict[str, Any]
    eligibility_counts: dict[str, int]
    truncation_applied: bool = False
    non_claims: tuple[str, ...] = ()
    schema: str = field(default="stpd/data-manifest-v0", init=False)

    def validate(self) -> None:
        if not self.manifest_id or not self.created_at or not self.source_revision:
            raise ContractError("manifest identity fields must be non-empty")
        if self.contract_schema != "stpd/research-transition-v0":
            raise ContractError("unsupported research transition contract")
        if not self.sources or not self.files or self.row_count <= 0:
            raise ContractError("manifest requires sources, files, and positive rows")
        for source in self.sources:
            source.validate()
        if sum(file.rows for file in self.files) != self.row_count:
            raise ContractError("manifest file row counts do not match row_count")
        if self.truncation_applied:
            raise ContractError("silent or declared truncation is inadmissible for v0")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        value = to_json_value(self)
        if not isinstance(value, dict):
            raise TypeError("manifest did not serialize to an object")
        return value

    @property
    def content_hash(self) -> str:
        return semantic_hash(self.to_dict())
