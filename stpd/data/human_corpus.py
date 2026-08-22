"""Deterministic multi-session Human Corpus admission and snapshot tooling.

This module composes the existing strict single-session importer. It does not
reinterpret recorder evidence or create a second Player Environment authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from ..canonical import canonical_json, semantic_hash
from ..representation import InputProfile, ModelSerializerV0
from .human_annotator import HumanImportReport, import_human_recording
from .manifest import DataSource
from .pipeline import build_canonical_dataset
from .splits import SplitAssignment

PROFILE_SCHEMA = "stpd/human-collection-profile-v1"
CAMPAIGN_SCHEMA = "stpd/human-collection-campaign-v1"
BUNDLE_SCHEMA = "sts2.human-annotator/session-bundle-1"
REGISTRY_SCHEMA = "stpd/human-session-registry-entry-v1"
CORPUS_IDENTITY_SCHEMA = "stpd/human-corpus-identity-v1"
CORPUS_REPORT_SCHEMA = "stpd/human-corpus-report-v1"
SMOKE_HANDOFF_SCHEMA = "stpd/human-smoke-handoff-v1"
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class HumanCorpusError(ValueError):
    """Fail-closed data-lane error."""


@dataclass(frozen=True)
class CollectionProfile:
    path: Path
    value: Mapping[str, Any]
    profile_id: str
    sha256: str

    @classmethod
    def load(cls, path: str | Path) -> CollectionProfile:
        source = Path(path).resolve()
        value = _load_object(source)
        if _text(value, "schema") != PROFILE_SCHEMA:
            raise HumanCorpusError("unsupported collection profile schema")
        profile_id = _identifier(value, "profile_id")
        _identifier(value, "platform")
        game = _object(value, "game")
        _text(game, "version")
        _text(game, "commit")
        _digest(game, "main_assembly_sha256")
        _uuid_text(game, "main_assembly_mvid")
        _validate_profile_artifact(_object(value, "connector"), "connector")
        _validate_profile_artifact(_object(value, "annotator"), "annotator")
        _text(value, "player_environment_protocol")
        modset = _object(value, "modset")
        _text(modset, "status")
        _digest(modset, "fingerprint")
        _text(value, "record_schema")
        families = _string_sequence(value, "allowed_action_families")
        if not families or len(families) != len(set(families)):
            raise HumanCorpusError(
                "collection profile action families must be non-empty and unique"
            )
        return cls(source, value, profile_id, semantic_hash(value))

    def validate_record(self, record: Mapping[str, Any]) -> None:
        if record.get("schema") != self.value["record_schema"]:
            raise HumanCorpusError("record schema drift")
        environment = _object(record, "environment")
        _require_fields_equal(_object(self.value, "game"), _object(environment, "game"), {
            "version": "version",
            "commit": "commit",
            "main_assembly_sha256": "main_assembly_sha256",
            "main_assembly_mvid": "main_assembly_module_version_id",
        }, "game")
        for name in ("connector", "annotator"):
            _require_fields_equal(_object(self.value, name), _object(environment, name), {
                "source_revision": "source_revision",
                "source_digest_sha256": "source_digest_sha256",
                "artifact_sha256": "sha256",
                "mvid": "module_version_id",
            }, name)
        if environment.get("player_environment_protocol") != self.value[
            "player_environment_protocol"
        ]:
            raise HumanCorpusError("Player Environment protocol drift")
        _require_fields_equal(_object(self.value, "modset"), environment, {
            "status": "modset_status",
            "fingerprint": "modset_fingerprint",
        }, "modset")
        action = _object(record, "action")
        family = (
            "ordinary_combat.play_card"
            if record.get("decision_family") == "ordinary_combat" and action.get("verb") == "play"
            else f"{record.get('decision_family')}.{action.get('verb')}"
        )
        if family not in _string_sequence(self.value, "allowed_action_families"):
            raise HumanCorpusError(f"record action family is outside profile: {family}")


@dataclass(frozen=True)
class CollectionCampaign:
    path: Path
    value: Mapping[str, Any]
    campaign_id: str
    profile_id: str
    sha256: str
    target_accepted_records: int
    allowed_workers: tuple[str, ...]

    @classmethod
    def load(cls, path: str | Path) -> CollectionCampaign:
        source = Path(path).resolve()
        value = _load_object(source)
        if _text(value, "schema") != CAMPAIGN_SCHEMA:
            raise HumanCorpusError("unsupported collection campaign schema")
        campaign_id = _identifier(value, "campaign_id")
        profile_id = _identifier(value, "collection_profile_id")
        target = _positive_int(value, "target_accepted_records")
        workers = tuple(_string_sequence(value, "allowed_workers"))
        if not workers or any(not _IDENTIFIER.fullmatch(worker) for worker in workers):
            raise HumanCorpusError("campaign requires pseudonymous allowed workers")
        if len(workers) != len(set(workers)):
            raise HumanCorpusError("campaign allowed workers must be unique")
        _text(value, "scope")
        _text(value, "created_at")
        return cls(
            source,
            value,
            campaign_id,
            profile_id,
            semantic_hash(value),
            target,
            workers,
        )


@dataclass(frozen=True)
class VerifiedSessionBundle:
    directory: Path
    manifest: Mapping[str, Any]
    session_id: str
    worker_id: str
    campaign_id: str
    profile_id: str
    content_id: str
    bundle_sha256: str
    export_sha256: str
    record_count: int
    run_ids: tuple[str, ...]
    invalidations: int
    invalidations_by_reason: Mapping[str, int]

    @property
    def export_path(self) -> Path:
        return self.directory / "export" / "decisions.jsonl"


@dataclass(frozen=True)
class SessionRegistryEntry:
    session_id: str
    worker_id: str
    collection_profile_id: str
    campaign_id: str
    bundle_uri: str
    bundle_content_id: str
    bundle_sha256: str
    export_sha256: str
    human_origin_attested: bool
    audit_status: str
    accepted_records: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": REGISTRY_SCHEMA,
            "session_id": self.session_id,
            "worker_id": self.worker_id,
            "collection_profile_id": self.collection_profile_id,
            "campaign_id": self.campaign_id,
            "bundle_uri": self.bundle_uri,
            "bundle_content_id": self.bundle_content_id,
            "bundle_sha256": self.bundle_sha256,
            "export_sha256": self.export_sha256,
            "human_origin_attested": self.human_origin_attested,
            "audit_status": self.audit_status,
            "accepted_records": self.accepted_records,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SessionRegistryEntry:
        if _text(value, "schema") != REGISTRY_SCHEMA:
            raise HumanCorpusError("unsupported session registry schema")
        result = cls(
            _identifier(value, "session_id"),
            _identifier(value, "worker_id"),
            _identifier(value, "collection_profile_id"),
            _identifier(value, "campaign_id"),
            _relative_uri(value, "bundle_uri"),
            _digest(value, "bundle_content_id"),
            _digest(value, "bundle_sha256"),
            _digest(value, "export_sha256"),
            _boolean(value, "human_origin_attested"),
            _text(value, "audit_status"),
            _positive_int(value, "accepted_records"),
        )
        if not result.human_origin_attested or result.audit_status != "pass":
            raise HumanCorpusError("registry entry is not human-attested and audit-passed")
        return result


@dataclass(frozen=True)
class CorpusBuildResult:
    status: Literal["built", "reused"]
    corpus_id: str
    snapshot_directory: Path
    accepted_records: int
    sessions: int
    b0_verdict: str


class LocalDirectorySessionStore:
    """Resolve portable bundle paths below one collection root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def resolve(self, bundle_uri: str) -> Path:
        relative = Path(bundle_uri)
        if relative.is_absolute() or ".." in relative.parts:
            raise HumanCorpusError("bundle URI must remain below the collection root")
        resolved = (self.root / relative).resolve()
        if not resolved.is_relative_to(self.root):
            raise HumanCorpusError("bundle URI escaped the collection root")
        return resolved


def verify_session_bundle(
    bundle_directory: str | Path, profile: CollectionProfile
) -> VerifiedSessionBundle:
    directory = Path(bundle_directory).resolve()
    if not directory.is_dir():
        raise HumanCorpusError(f"session bundle is absent: {directory}")
    checksums_path = directory / "checksums.sha256"
    checksums = _read_checksums(checksums_path)
    actual_files = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path != checksums_path
    }
    if set(checksums) != actual_files:
        raise HumanCorpusError("bundle file inventory differs from checksums.sha256")
    for relative, expected in checksums.items():
        if _sha256_file(directory / relative) != expected:
            raise HumanCorpusError(f"bundle checksum mismatch: {relative}")

    manifest = _load_object(directory / "session-bundle-manifest.json")
    if _text(manifest, "schema") != BUNDLE_SCHEMA or manifest.get("schema_version") != 1:
        raise HumanCorpusError("unsupported session bundle schema")
    content_identity = _object(manifest, "content_identity")
    content_id = _digest(manifest, "bundle_content_id")
    if semantic_hash(content_identity) != content_id:
        raise HumanCorpusError("bundle content identity mismatch")
    embedded_profile = _load_object(directory / "profile" / "collection-profile.json")
    if embedded_profile != profile.value or semantic_hash(embedded_profile) != profile.sha256:
        raise HumanCorpusError("embedded collection profile differs from admitted profile")
    if _text(manifest, "collection_profile_id") != profile.profile_id:
        raise HumanCorpusError("bundle collection profile ID drift")
    if _digest(manifest, "collection_profile_sha256") != profile.sha256:
        raise HumanCorpusError("bundle collection profile digest drift")
    attestation = _object(manifest, "human_origin_attestation")
    if not _boolean(attestation, "attested") or attestation.get("machine_verifiable") is not False:
        raise HumanCorpusError("bundle has no explicit human-origin attestation")
    worker_id = _identifier(manifest, "worker_id")
    if attestation.get("worker_id") != worker_id:
        raise HumanCorpusError("attestation worker differs from bundle worker")
    if _text(manifest, "audit_status") != "pass":
        raise HumanCorpusError("bundle audit did not pass")
    audit = _load_object(directory / "audit" / "audit-report.json")
    if audit.get("status") != "pass" or audit.get("invalid_records") != 0:
        raise HumanCorpusError("independent bundle audit report did not pass")
    record_count = _positive_int(manifest, "record_count")
    if audit.get("valid_records") != record_count:
        raise HumanCorpusError("bundle audit count differs from manifest")
    export_sha = _sha256_file(directory / "export" / "decisions.jsonl")
    if export_sha != _digest(manifest, "export_sha256"):
        raise HumanCorpusError("bundle export digest differs from manifest")
    recording = _load_object(directory / "raw" / "recording-manifest.json")
    session_id = _identifier(manifest, "session_id")
    if recording.get("session_id") != session_id:
        raise HumanCorpusError("raw recording manifest session differs from bundle")
    if recording.get("platform") != profile.value["platform"]:
        raise HumanCorpusError("raw recording platform differs from profile")
    coverage = _load_object(directory / "raw" / "coverage.json")
    if coverage.get("session_id") != session_id or coverage.get("admitted_records") != record_count:
        raise HumanCorpusError("raw coverage differs from bundle manifest")
    run_ids = tuple(_string_sequence(manifest, "run_ids"))
    if not run_ids or len(run_ids) != len(set(run_ids)):
        raise HumanCorpusError("bundle run IDs must be non-empty and unique")
    expected_runs = {f"raw/{run_id}.jsonl" for run_id in run_ids}
    if not expected_runs.issubset(actual_files):
        raise HumanCorpusError("bundle is missing a declared raw run")

    raw_lines = [
        line
        for run_id in sorted(run_ids)
        for line in (directory / "raw" / f"{run_id}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    expected_export = "".join(f"{line}\n" for line in raw_lines).encode("utf-8")
    if (directory / "export" / "decisions.jsonl").read_bytes() != expected_export:
        raise HumanCorpusError("bundle export is not the deterministic raw-session export")

    raw_directory = directory / "raw"
    raw_file_sha256 = {
        path.name: _sha256_file(path)
        for path in sorted(raw_directory.iterdir())
        if path.is_file()
    }
    expected_content_identity = {
        "schema": BUNDLE_SCHEMA,
        "session_id": session_id,
        "collection_profile_id": profile.profile_id,
        "collection_profile_sha256": profile.sha256,
        "campaign_id": _identifier(manifest, "campaign_id"),
        "worker_id": worker_id,
        "human_origin_attestation": dict(attestation),
        "record_count": record_count,
        "run_ids": list(run_ids),
        "export_sha256": export_sha,
        "raw_file_sha256": raw_file_sha256,
        "audit": {
            "status": audit.get("status"),
            "valid_records": audit.get("valid_records"),
            "invalid_records": audit.get("invalid_records"),
            "invalidations": audit.get("invalidations"),
        },
    }
    if content_identity != expected_content_identity:
        raise HumanCorpusError("bundle content identity differs from verified bundle facts")

    export_records = _jsonl(directory / "export" / "decisions.jsonl")
    if len(export_records) != record_count:
        raise HumanCorpusError("bundle export record count differs from manifest")
    observed_run_ids: set[str] = set()
    for line_number, record in export_records:
        if record.get("session_id") != session_id:
            raise HumanCorpusError(f"export line {line_number} has another session ID")
        observed_run_ids.add(_identifier(record, "run_id"))
        profile.validate_record(record)
    if observed_run_ids != set(run_ids):
        raise HumanCorpusError("bundle export run IDs differ from manifest")
    invalidations_by_reason = {
        str(key): int(value)
        for key, value in _object(coverage, "invalidations_by_reason").items()
    }
    return VerifiedSessionBundle(
        directory,
        manifest,
        session_id,
        worker_id,
        _identifier(manifest, "campaign_id"),
        profile.profile_id,
        content_id,
        _sha256_file(checksums_path),
        export_sha,
        record_count,
        run_ids,
        int(audit.get("invalidations", 0)),
        invalidations_by_reason,
    )


def register_session_bundle(
    *,
    collection_root: str | Path,
    bundle_directory: str | Path,
    registry_directory: str | Path,
    profile: CollectionProfile,
    campaign: CollectionCampaign,
) -> tuple[SessionRegistryEntry, Literal["created", "reused"]]:
    root = Path(collection_root).resolve()
    bundle = verify_session_bundle(bundle_directory, profile)
    if bundle.campaign_id != campaign.campaign_id or campaign.profile_id != profile.profile_id:
        raise HumanCorpusError("bundle campaign/profile differs from the registry campaign")
    if bundle.worker_id not in campaign.allowed_workers:
        raise HumanCorpusError("bundle worker is not admitted by the campaign")
    try:
        bundle_uri = bundle.directory.relative_to(root).as_posix()
    except ValueError as error:
        raise HumanCorpusError("bundle must be stored below collection_root") from error
    entry = SessionRegistryEntry(
        bundle.session_id,
        bundle.worker_id,
        profile.profile_id,
        campaign.campaign_id,
        bundle_uri,
        bundle.content_id,
        bundle.bundle_sha256,
        bundle.export_sha256,
        True,
        "pass",
        bundle.record_count,
    )
    registry = Path(registry_directory).resolve()
    registry.mkdir(parents=True, exist_ok=True)
    destination = registry / f"{bundle.session_id}.json"
    encoded = canonical_json(entry.to_dict()) + "\n"
    if destination.exists():
        if destination.read_text(encoding="utf-8") != encoded:
            raise HumanCorpusError("immutable registry entry already exists with different content")
        return entry, "reused"
    _atomic_write(destination, encoded)
    return entry, "created"


def build_human_corpus(
    *,
    collection_root: str | Path,
    registry_directory: str | Path,
    profile: CollectionProfile,
    campaign: CollectionCampaign,
    output_root: str | Path,
    schema_root: str | Path,
    stpd_source_revision: str,
    split_salt: str,
    tokenizer_path: str | Path | None = None,
    tokenizer_revision: str | None = None,
) -> CorpusBuildResult:
    if not _COMMIT.fullmatch(stpd_source_revision):
        raise HumanCorpusError("STPD source revision must be an exact Git SHA")
    if not split_salt:
        raise HumanCorpusError("corpus split salt must be explicit")
    if campaign.profile_id != profile.profile_id:
        raise HumanCorpusError("campaign and collection profile differ")
    entries = _read_registry(registry_directory)
    if not entries:
        raise HumanCorpusError("session registry is empty")
    store = LocalDirectorySessionStore(collection_root)
    sessions: list[tuple[SessionRegistryEntry, VerifiedSessionBundle, HumanImportReport]] = []
    seen_sessions: set[str] = set()
    seen_bundle_content_ids: set[str] = set()
    seen_bundle_checksums: set[str] = set()
    seen_exports: set[str] = set()
    for entry in entries:
        if entry.session_id in seen_sessions:
            raise HumanCorpusError(f"duplicate session ID: {entry.session_id}")
        if entry.bundle_content_id in seen_bundle_content_ids:
            raise HumanCorpusError(f"duplicate session bundle content: {entry.session_id}")
        if entry.bundle_sha256 in seen_bundle_checksums:
            raise HumanCorpusError(f"duplicate session bundle: {entry.session_id}")
        if entry.export_sha256 in seen_exports:
            raise HumanCorpusError(f"duplicate session export: {entry.session_id}")
        if entry.collection_profile_id != profile.profile_id:
            raise HumanCorpusError(f"registry profile drift: {entry.session_id}")
        if entry.campaign_id != campaign.campaign_id:
            raise HumanCorpusError(f"registry campaign drift: {entry.session_id}")
        if entry.worker_id not in campaign.allowed_workers:
            raise HumanCorpusError(f"registry worker is not admitted: {entry.worker_id}")
        bundle = verify_session_bundle(store.resolve(entry.bundle_uri), profile)
        _require_registry_matches_bundle(entry, bundle)
        report = import_human_recording(
            bundle.export_path,
            provenance_uri=f"bundle://{bundle.content_id}/export/decisions.jsonl",
        )
        if report.rejected_count or report.accepted_count != bundle.record_count:
            raise HumanCorpusError(
                f"strict single-session import failed for {entry.session_id}: "
                f"accepted={report.accepted_count}, rejected={report.rejected_count}"
            )
        sessions.append((entry, bundle, report))
        seen_sessions.add(entry.session_id)
        seen_bundle_content_ids.add(entry.bundle_content_id)
        seen_bundle_checksums.add(entry.bundle_sha256)
        seen_exports.add(entry.export_sha256)

    transition_ids: set[str] = set()
    record_ids: set[str] = set()
    transitions = []
    for _, _, report in sessions:
        for imported in report.accepted:
            if imported.record_id in record_ids:
                raise HumanCorpusError(f"global human record collision: {imported.record_id}")
            if imported.transition.transition_id in transition_ids:
                raise HumanCorpusError(
                    f"global transition collision: {imported.transition.transition_id}"
                )
            record_ids.add(imported.record_id)
            transition_ids.add(imported.transition.transition_id)
            transitions.append(imported.transition)
    transitions.sort(key=lambda item: (item.episode_id, item.step_index, item.transition_id))
    records = [transition.to_dict() for transition in transitions]
    assignments, duplicate_report = _assign_corpus_splits(records, split_salt)
    sources = tuple(
        DataSource(
            source_id=f"human-session-{bundle.content_id[:16]}",
            kind="human_native_ui_session_bundle",
            source_revision=bundle.export_sha256,
            license_spdx="LicenseRef-Private-Human-Data",
            provenance_uri=f"bundle://{bundle.content_id}",
        )
        for _, bundle, _ in sorted(sessions, key=lambda item: item[1].session_id)
    )

    output = Path(output_root).resolve()
    snapshots = output / profile.profile_id / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".corpus-tmp-", dir=snapshots))
    try:
        manifest, b0 = build_canonical_dataset(
            records,
            output_dir=temporary,
            schema_root=schema_root,
            sources=sources,
            stpd_source_revision=stpd_source_revision,
            created_at=_text(campaign.value, "created_at"),
            split_salt=split_salt,
            split_assignments=assignments,
            split_strategy="whole_run_semantic_component_sha256_v1",
            deduplication=duplicate_report,
        )
        source_registry = {
            "schema": "stpd/human-corpus-source-registry-v1",
            "collection_profile_id": profile.profile_id,
            "campaign_id": campaign.campaign_id,
            "sessions": [entry.to_dict() for entry, _, _ in sorted(
                sessions, key=lambda item: item[0].session_id
            )],
        }
        _write_canonical(temporary / "source-registry.json", source_registry)
        _write_canonical(temporary / "b0-report.json", b0.to_dict())
        token_report = None
        if tokenizer_path is not None:
            token_report = _profile_standard_tokens(
                transitions,
                Path(tokenizer_path),
                tokenizer_revision=tokenizer_revision,
            )
            _write_canonical(temporary / "token-profile-report.json", token_report)
        corpus_report = _corpus_report(
            sessions,
            transitions,
            assignments,
            duplicate_report,
            b0.to_dict(),
            token_report,
            campaign.target_accepted_records,
        )
        identity = {
            "schema": CORPUS_IDENTITY_SCHEMA,
            "collection_profile_id": profile.profile_id,
            "collection_profile_sha256": profile.sha256,
            "campaign_id": campaign.campaign_id,
            "campaign_sha256": campaign.sha256,
            "campaign_target_accepted_records": campaign.target_accepted_records,
            "session_bundle_content_ids": sorted(bundle.content_id for _, bundle, _ in sessions),
            "session_export_sha256": sorted(bundle.export_sha256 for _, bundle, _ in sessions),
            "stpd_source_revision": stpd_source_revision,
            "split_salt_sha256": semantic_hash(split_salt),
            "split_assignments_sha256": manifest.split["assignments_hash"],
            "dataset_manifest_sha256": _sha256_file(temporary / "manifest.json"),
            "parquet_sha256": _sha256_file(temporary / "transitions.parquet"),
            "tokenizer_sha256": None if token_report is None else token_report["tokenizer_sha256"],
            "tokenizer_revision": (
                None if token_report is None else token_report["tokenizer_revision"]
            ),
            "serializer_version": ModelSerializerV0.version,
        }
        corpus_id = semantic_hash(identity)
        identity = {**identity, "corpus_id": corpus_id}
        corpus_report = {**corpus_report, "corpus_id": corpus_id}
        _write_canonical(temporary / "corpus-identity.json", identity)
        _write_canonical(temporary / "corpus-report.json", corpus_report)
        _write_checksums(temporary)
        destination = snapshots / f"corpus-{corpus_id[:16]}"
        if destination.exists():
            if not _directories_equal(temporary, destination):
                raise HumanCorpusError("immutable corpus ID exists with different bytes")
            shutil.rmtree(temporary)
            status: Literal["built", "reused"] = "reused"
        else:
            os.replace(temporary, destination)
            status = "built"
        return CorpusBuildResult(
            status,
            corpus_id,
            destination,
            len(records),
            len(sessions),
            b0.verdict,
        )
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def freeze_smoke_handoff(
    *, snapshot_directory: str | Path, output_root: str | Path, minimum_records: int
) -> Path:
    snapshot = Path(snapshot_directory).resolve()
    _verify_checksums(snapshot)
    identity = _load_object(snapshot / "corpus-identity.json")
    report = _load_object(snapshot / "corpus-report.json")
    manifest = _load_object(snapshot / "manifest.json")
    token_report = _load_object(snapshot / "token-profile-report.json")
    if report.get("b0", {}).get("verdict") != "pass":
        raise HumanCorpusError("smoke handoff requires corpus-level B0 pass")
    campaign_target = _positive_int(identity, "campaign_target_accepted_records")
    required_records = max(minimum_records, campaign_target)
    if int(report.get("accepted_records", 0)) < required_records:
        raise HumanCorpusError(
            f"smoke handoff requires at least {required_records} accepted records"
        )
    if token_report.get("passed") is not True:
        raise HumanCorpusError("smoke handoff requires a passing Standard token profile")
    if report.get("deduplication", {}).get("cross_split_semantic_duplicates") != 0:
        raise HumanCorpusError("smoke handoff forbids cross-split semantic duplicates")
    handoff_identity = {
        "schema": SMOKE_HANDOFF_SCHEMA,
        "corpus_id": _digest(identity, "corpus_id"),
        "corpus_directory_name": snapshot.name,
        "collection_profile_id": _text(identity, "collection_profile_id"),
        "collection_profile_sha256": _digest(identity, "collection_profile_sha256"),
        "campaign_id": _text(identity, "campaign_id"),
        "campaign_sha256": _digest(identity, "campaign_sha256"),
        "accepted_records": int(report["accepted_records"]),
        "campaign_target_accepted_records": campaign_target,
        "minimum_records": required_records,
        "parquet_sha256": _sha256_file(snapshot / "transitions.parquet"),
        "manifest_sha256": _sha256_file(snapshot / "manifest.json"),
        "source_registry_sha256": _sha256_file(snapshot / "source-registry.json"),
        "split_assignments_sha256": manifest["split"]["assignments_hash"],
        "b0_report_sha256": _sha256_file(snapshot / "b0-report.json"),
        "token_profile_sha256": _sha256_file(snapshot / "token-profile-report.json"),
        "stpd_source_revision": _text(identity, "stpd_source_revision"),
        "serializer_version": _text(identity, "serializer_version"),
        "tokenizer_sha256": _digest(identity, "tokenizer_sha256"),
        "tokenizer_revision": _text(identity, "tokenizer_revision"),
        "training_authorized": False,
        "non_claims": [
            "Frozen data does not authorize training.",
            "B0 and token profiling do not prove human label quality.",
        ],
    }
    handoff_id = semantic_hash(handoff_identity)
    document = {**handoff_identity, "handoff_id": handoff_id}
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"smoke-handoff-{handoff_id[:16]}"
    encoded = canonical_json(document) + "\n"
    if destination.exists():
        if (destination / "handoff.json").read_text(encoding="utf-8") != encoded:
            raise HumanCorpusError("immutable smoke handoff exists with different bytes")
        return destination
    temporary = Path(tempfile.mkdtemp(prefix=".handoff-tmp-", dir=root))
    try:
        _atomic_write(temporary / "handoff.json", encoded)
        _write_checksums(temporary)
        os.replace(temporary, destination)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return destination


def inspect_corpus_snapshot(snapshot_directory: str | Path) -> dict[str, Any]:
    snapshot = Path(snapshot_directory).resolve()
    _verify_checksums(snapshot)
    identity = _load_object(snapshot / "corpus-identity.json")
    report = _load_object(snapshot / "corpus-report.json")
    manifest = _load_object(snapshot / "manifest.json")
    if snapshot.name != f"corpus-{_digest(identity, 'corpus_id')[:16]}":
        raise HumanCorpusError("corpus directory name differs from content identity")
    if report.get("corpus_id") != identity["corpus_id"]:
        raise HumanCorpusError("corpus report differs from content identity")
    if manifest.get("row_count") != report.get("accepted_records"):
        raise HumanCorpusError("corpus report row count differs from dataset manifest")
    return {
        "status": "pass",
        "snapshot_directory": str(snapshot),
        "corpus_id": identity["corpus_id"],
        "accepted_records": report["accepted_records"],
        "sessions": report["sessions"],
        "b0_verdict": report["b0"]["verdict"],
        "checksums_sha256": _sha256_file(snapshot / "checksums.sha256"),
    }


def _assign_corpus_splits(
    records: Sequence[Mapping[str, Any]], salt: str
) -> tuple[dict[str, SplitAssignment], dict[str, Any]]:
    episode_roots: dict[str, str] = {}
    parent: dict[str, str] = {}
    semantic_episodes: defaultdict[str, set[str]] = defaultdict(set)
    exact_counts: Counter[str] = Counter()
    for record in records:
        episode = _text(record, "episode_id")
        root = _text(record, "seed")
        previous = episode_roots.setdefault(episode, root)
        if previous != root:
            raise HumanCorpusError(f"episode spans multiple whole-run roots: {episode}")
        parent.setdefault(root, root)
        fingerprint = semantic_hash({
            "state": record["state"],
            "legal_actions": record["legal_actions"],
            "chosen_action": record["chosen_action"],
        })
        semantic_episodes[fingerprint].add(episode)
        exact_counts[semantic_hash(record)] += 1

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for episodes in semantic_episodes.values():
        roots = sorted({episode_roots[episode] for episode in episodes})
        for root in roots[1:]:
            union(roots[0], root)
    components: defaultdict[str, list[str]] = defaultdict(list)
    for root in sorted(parent):
        components[find(root)].append(root)
    root_splits: dict[str, Literal["train", "dev", "test"]] = {}
    for roots in components.values():
        key = semantic_hash(roots)
        bucket = int.from_bytes(
            hashlib.sha256(f"{salt}\0{key}".encode()).digest()[:8], "big"
        ) % 10_000
        split: Literal["train", "dev", "test"] = (
            "train" if bucket < 8000 else "dev" if bucket < 9000 else "test"
        )
        for root in roots:
            root_splits[root] = split
    assignments = {
        episode: SplitAssignment(episode, root, root_splits[root])
        for episode, root in sorted(episode_roots.items())
    }
    cross_session = 0
    semantic_duplicates = 0
    for episodes in semantic_episodes.values():
        if len(episodes) > 1:
            semantic_duplicates += 1
            sessions = {episode.removeprefix("human:").split("/", 1)[0] for episode in episodes}
            if len(sessions) > 1:
                cross_session += 1
    return assignments, {
        "exact_record_duplicates": sum(count - 1 for count in exact_counts.values() if count > 1),
        "semantic_duplicate_groups": semantic_duplicates,
        "cross_session_semantic_duplicate_groups": cross_session,
        "cross_split_semantic_duplicates": 0,
        "decision_fingerprint": "state+legal_actions+chosen_action-v0",
        "split_grouping": "whole_run+semantic_duplicate_component-v1",
    }


def _corpus_report(
    sessions: Sequence[tuple[SessionRegistryEntry, VerifiedSessionBundle, HumanImportReport]],
    transitions: Sequence[Any],
    assignments: Mapping[str, SplitAssignment],
    duplicate_report: Mapping[str, Any],
    b0: Mapping[str, Any],
    token_report: Mapping[str, Any] | None,
    target_accepted_records: int,
) -> dict[str, Any]:
    action_counts = Counter(transition.chosen_action.kind for transition in transitions)
    targeted = sum(
        1
        for transition in transitions
        if transition.chosen_action.kind == "play" and transition.chosen_action.arguments
    )
    untargeted = sum(
        1
        for transition in transitions
        if transition.chosen_action.kind == "play" and not transition.chosen_action.arguments
    )
    catalog_sizes = [len(transition.legal_actions) for transition in transitions]
    invalidations: Counter[str] = Counter()
    per_session = []
    for entry, bundle, _ in sorted(sessions, key=lambda item: item[0].session_id):
        invalidations.update(bundle.invalidations_by_reason)
        per_session.append({
            "session_id": entry.session_id,
            "worker_id": entry.worker_id,
            "accepted_records": entry.accepted_records,
            "invalidations": bundle.invalidations,
            "run_ids": list(bundle.run_ids),
            "export_sha256": bundle.export_sha256,
        })
    split_counts = Counter(assignment.split for assignment in assignments.values())
    return {
        "schema": CORPUS_REPORT_SCHEMA,
        "accepted_records": len(transitions),
        "target_accepted_records": target_accepted_records,
        "records_remaining": max(0, target_accepted_records - len(transitions)),
        "sessions": len(sessions),
        "runs": len(assignments),
        "workers": len({entry.worker_id for entry, _, _ in sessions}),
        "environments": int(b0["environment_count"]),
        "action_counts": dict(sorted(action_counts.items())),
        "targeted_play": targeted,
        "untargeted_play": untargeted,
        "catalog_size": _distribution(catalog_sizes),
        "split_episode_counts": dict(sorted(split_counts.items())),
        "per_session": per_session,
        "invalidations_by_reason": dict(sorted(invalidations.items())),
        "deduplication": dict(duplicate_report),
        "b0": dict(b0),
        "standard_token_profile": token_report,
    }


def _profile_standard_tokens(
    transitions: Sequence[Any],
    tokenizer_path: Path,
    *,
    tokenizer_revision: str | None,
) -> dict[str, Any]:
    from ..qwen.l1 import QwenL1Error, profile_records

    serializer = ModelSerializerV0(InputProfile.STANDARD)
    samples = []
    for transition in transitions:
        state = serializer.serialize_state(transition.state)
        for action in transition.legal_actions:
            samples.append({
                "profile": InputProfile.STANDARD.value,
                "family": transition.state.decision_family.value,
                "text": f"{state}\n{serializer.serialize_action(action)}",
            })
    try:
        report = profile_records(tokenizer_path, samples)
    except QwenL1Error as error:
        raise HumanCorpusError(f"Standard token profiling failed: {error}") from error
    return {
        **report,
        "serializer_version": serializer.version,
        "input_profile": InputProfile.STANDARD.value,
        "tokenizer_revision": tokenizer_revision or "explicit-local-tokenizer-file",
    }


def _read_registry(directory: str | Path) -> list[SessionRegistryEntry]:
    root = Path(directory).resolve()
    if not root.is_dir():
        raise HumanCorpusError("session registry directory is absent")
    entries = [
        SessionRegistryEntry.from_dict(_load_object(path))
        for path in sorted(root.glob("*.json"))
    ]
    return sorted(entries, key=lambda entry: (
        entry.session_id,
        entry.bundle_content_id,
        entry.bundle_uri,
    ))


def _require_registry_matches_bundle(
    entry: SessionRegistryEntry, bundle: VerifiedSessionBundle
) -> None:
    expected = {
        "session_id": bundle.session_id,
        "worker_id": bundle.worker_id,
        "collection_profile_id": bundle.profile_id,
        "campaign_id": bundle.campaign_id,
        "bundle_content_id": bundle.content_id,
        "bundle_sha256": bundle.bundle_sha256,
        "export_sha256": bundle.export_sha256,
        "accepted_records": bundle.record_count,
    }
    for field, value in expected.items():
        if getattr(entry, field) != value:
            raise HumanCorpusError(f"registry/bundle mismatch: {field}")


def _validate_profile_artifact(value: Mapping[str, Any], name: str) -> None:
    if not _COMMIT.fullmatch(_text(value, "source_revision")):
        raise HumanCorpusError(f"{name} source revision is not exact")
    _digest(value, "source_digest_sha256")
    _digest(value, "artifact_sha256")
    _uuid_text(value, "mvid")


def _require_fields_equal(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    fields: Mapping[str, str],
    label: str,
) -> None:
    for expected_name, actual_name in fields.items():
        if expected.get(expected_name) != actual.get(actual_name):
            raise HumanCorpusError(f"{label} identity drift: {expected_name}")


def _read_checksums(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise HumanCorpusError("bundle checksums.sha256 is absent")
    result: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            continue
        digest, separator, relative = line.partition("  ")
        if not separator or not _SHA256.fullmatch(digest) or not relative:
            raise HumanCorpusError(f"invalid checksum line {number}")
        if relative in result or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise HumanCorpusError(f"unsafe or duplicate checksum path: {relative}")
        result[relative] = digest
    if not result:
        raise HumanCorpusError("checksums.sha256 is empty")
    return result


def _verify_checksums(directory: Path) -> None:
    expected = _read_checksums(directory / "checksums.sha256")
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.name != "checksums.sha256"
    }
    if set(expected) != actual:
        raise HumanCorpusError("snapshot file inventory differs from checksums")
    for relative, digest in expected.items():
        if _sha256_file(directory / relative) != digest:
            raise HumanCorpusError(f"snapshot checksum mismatch: {relative}")


def _write_checksums(directory: Path) -> None:
    files = sorted(
        path for path in directory.rglob("*") if path.is_file() and path.name != "checksums.sha256"
    )
    content = "".join(
        f"{_sha256_file(path)}  {path.relative_to(directory).as_posix()}\n" for path in files
    )
    _atomic_write(directory / "checksums.sha256", content)


def _directories_equal(left: Path, right: Path) -> bool:
    left_files = sorted(
        path.relative_to(left).as_posix() for path in left.rglob("*") if path.is_file()
    )
    right_files = sorted(
        path.relative_to(right).as_posix() for path in right.rglob("*") if path.is_file()
    )
    return left_files == right_files and all(
        _sha256_file(left / relative) == _sha256_file(right / relative)
        for relative in left_files
    )


def _distribution(values: Sequence[int]) -> dict[str, int]:
    if not values:
        return {"min": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0}
    ordered = sorted(values)

    def rank(quantile: float) -> int:
        index = max(0, min(len(ordered) - 1, int(len(ordered) * quantile + 0.999999) - 1))
        return ordered[index]

    return {
        "min": ordered[0],
        "p50": rank(0.50),
        "p95": rank(0.95),
        "p99": rank(0.99),
        "max": ordered[-1],
    }


def _jsonl(path: Path) -> list[tuple[int, Mapping[str, Any]]]:
    result = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise HumanCorpusError(f"invalid JSONL at {path}:{number}: {error}") from error
        if not isinstance(value, Mapping):
            raise HumanCorpusError(f"JSONL record is not an object at {path}:{number}")
        result.append((number, cast(Mapping[str, Any], value)))
    return result


def _load_object(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HumanCorpusError(f"cannot read JSON object {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise HumanCorpusError(f"JSON document is not an object: {path}")
    return cast(Mapping[str, Any], value)


def _write_canonical(path: Path, value: Any) -> None:
    _atomic_write(path, canonical_json(value) + "\n")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = hashlib.sha256(content.encode()).hexdigest()[:12]
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{suffix}")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise HumanCorpusError(f"missing object: {key}")
    return cast(Mapping[str, Any], item)


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise HumanCorpusError(f"missing text: {key}")
    return item


def _identifier(value: Mapping[str, Any], key: str) -> str:
    item = _text(value, key)
    if not _IDENTIFIER.fullmatch(item):
        raise HumanCorpusError(f"invalid pseudonymous identifier: {key}")
    return item


def _relative_uri(value: Mapping[str, Any], key: str) -> str:
    item = _text(value, key)
    path = Path(item)
    if path.is_absolute() or ".." in path.parts:
        raise HumanCorpusError(f"invalid relative bundle URI: {item}")
    return path.as_posix()


def _digest(value: Mapping[str, Any], key: str) -> str:
    item = _text(value, key)
    if not _SHA256.fullmatch(item):
        raise HumanCorpusError(f"invalid SHA-256: {key}")
    return item


def _uuid_text(value: Mapping[str, Any], key: str) -> str:
    item = _text(value, key)
    if not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        item,
    ):
        raise HumanCorpusError(f"invalid UUID: {key}")
    return item


def _positive_int(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
        raise HumanCorpusError(f"invalid positive integer: {key}")
    return item


def _boolean(value: Mapping[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise HumanCorpusError(f"invalid boolean: {key}")
    return item


def _string_sequence(value: Mapping[str, Any], key: str) -> tuple[str, ...]:
    item = value.get(key)
    if not isinstance(item, Sequence) or isinstance(item, (str, bytes)):
        raise HumanCorpusError(f"missing string array: {key}")
    result = tuple(item)
    if any(not isinstance(entry, str) or not entry for entry in result):
        raise HumanCorpusError(f"invalid string array: {key}")
    return cast(tuple[str, ...], result)
