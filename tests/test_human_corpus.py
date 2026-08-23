from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from stpd.canonical import canonical_json, semantic_hash
from stpd.data.human_corpus import (
    CollectionCampaign,
    CollectionProfile,
    HumanCorpusError,
    build_human_corpus,
    freeze_smoke_handoff,
    inspect_corpus_snapshot,
    register_session_bundle,
    verify_session_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "collection-profiles" / "human-mac-combat-v1.json"
CAMPAIGN_PATH = ROOT / "collection-campaigns" / "human-combat-smoke-2026-08.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _snapshot(
    snapshot_id: str,
    interaction_id: str,
    *,
    state_marker: str,
    chosen_bound_id: str,
) -> dict[str, Any]:
    actions = [
        {
            "bound_action_id": chosen_bound_id,
            "verb": "play",
            "interaction_id": interaction_id,
            "subject_referent_id": "card-1",
            "arguments": [],
            "label": "Play Strike",
        },
        {
            "bound_action_id": f"end-{state_marker}",
            "verb": "end_turn",
            "interaction_id": interaction_id,
            "subject_referent_id": None,
            "arguments": [],
            "label": "End turn",
        },
    ]
    return {
        "protocol_version": "1.0.0",
        "schema": "sts2.player-environment/snapshot-1",
        "snapshot_id": snapshot_id,
        "sequence": 1,
        "observed_at": "2026-08-23T00:00:00Z",
        "status": "interactive",
        "persistent": {"kind": "run", "hp": 50, "marker": state_marker},
        "interaction": {
            "interaction_id": interaction_id,
            "kind": "combat_turn",
            "stage": "choosing",
            "prompt": None,
            "content_schema": "sts2.player-environment/surface/combat-turn-1",
            "content": {"surface": {"kind": "combat_turn"}, "context": {"kind": "combat"}},
            "capabilities": [],
        },
        "referents": [
            {
                "referent_id": "card-1",
                "role": "hand_card",
                "kind": "card",
                "label": "Strike",
                "state": {
                    "visible": True,
                    "enabled": True,
                    "selected": False,
                    "focused": False,
                    "observation_basis": "native_ui",
                },
                "properties_schema": "card-1",
                "properties": {"name": "Strike", "current_cost": 1},
            }
        ],
        "bound_actions": {
            "schema": "sts2.player-environment/bound-actions-1",
            "status": "complete",
            "materialized_count": 2,
            "total_count": 2,
            "limit": 512,
            "ordering_semantics": "fixture",
            "actions": actions,
        },
        "reads": [],
        "completeness": {
            "status": "complete",
            "visible_information": "complete",
            "interaction_discovery": "complete",
            "missing": [],
            "hidden_by_policy": [],
        },
        "session": {
            "runtime_instance_id": "runtime-1",
            "environment_fingerprint": "environment-1",
        },
        "information_policy": {
            "id": "player_visible_v1",
            "scope": "fair_player",
            "includes_hidden_information": False,
            "unknown_field_behavior": "omit",
        },
    }


def _record(
    profile: CollectionProfile,
    *,
    session_id: str,
    run_id: str,
    record_id: str,
    sequence: int,
    state_marker: str,
) -> dict[str, Any]:
    chosen_bound_id = f"bound-{state_marker}"
    pre = _snapshot(
        f"snapshot-{session_id}-{sequence}-a",
        f"interaction-{session_id}-{sequence}-a",
        state_marker=state_marker,
        chosen_bound_id=chosen_bound_id,
    )
    successor = _snapshot(
        f"snapshot-{session_id}-{sequence}-b",
        f"interaction-{session_id}-{sequence}-b",
        state_marker=f"{state_marker}-successor",
        chosen_bound_id=f"next-{state_marker}",
    )
    profile_value = profile.value
    game = profile_value["game"]
    connector_profile = profile_value["connector"]
    annotator_profile = profile_value["annotator"]
    connector = {
        "product": "STS2 Player Environment",
        "version": "1.1.0-rc.1",
        "source_revision": connector_profile["source_revision"],
        "source_digest_sha256": connector_profile["source_digest_sha256"],
        "sha256": connector_profile["artifact_sha256"],
        "module_version_id": connector_profile["mvid"],
    }
    annotator = {
        "product": "STS2 Native UI Human Annotator",
        "version": "0.1.0",
        "source_revision": annotator_profile["source_revision"],
        "source_digest_sha256": annotator_profile["source_digest_sha256"],
        "sha256": annotator_profile["artifact_sha256"],
        "module_version_id": annotator_profile["mvid"],
    }
    catalog_digest = hashlib.sha256(
        json.dumps(
            pre["bound_actions"], ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "schema": "sts2.human-annotator/decision-record-1",
        "record_id": record_id,
        "session_id": session_id,
        "run_id": run_id,
        "sequence": sequence,
        "recorded_at": "2026-08-23T00:00:01Z",
        "environment": {
            "game": {
                "version": game["version"],
                "commit": game["commit"],
                "main_assembly_sha256": game["main_assembly_sha256"],
                "main_assembly_module_version_id": game["main_assembly_mvid"],
            },
            "connector": connector,
            "annotator": annotator,
            "player_environment_protocol": profile_value["player_environment_protocol"],
            "runtime_instance_id": "runtime-1",
            "environment_fingerprint": "environment-1",
            "modset_status": profile_value["modset"]["status"],
            "modset_fingerprint": profile_value["modset"]["fingerprint"],
        },
        "pre": {
            "snapshot_id": pre["snapshot_id"],
            "interaction_id": pre["interaction"]["interaction_id"],
            "interaction_kind": "combat_turn",
            "surface_schema": pre["interaction"]["content_schema"],
            "catalog_digest": catalog_digest,
            "catalog_count": 2,
            "snapshot": pre,
        },
        "native_witness": {
            "origin": "native_card_play_ui",
            "native_action_type": "PlayCardAction",
            "subject_witness_id": "native-card-1",
            "argument_witness_ids": {},
            "accepted_at": "2026-08-23T00:00:00Z",
        },
        "mapping": {
            "status": "exact_unique",
            "match_count": 1,
            "basis": "reference_equality_to_frozen_host_binding",
            "detail": None,
        },
        "action": {
            "bound_action_id": chosen_bound_id,
            "verb": "play",
            "subject_referent_id": "card-1",
            "arguments": {},
            "label": "Play Strike",
        },
        "successor": {
            "snapshot_id": successor["snapshot_id"],
            "status": "interactive",
            "interaction_id": successor["interaction"]["interaction_id"],
            "interaction_kind": "combat_turn",
            "observed_at": "2026-08-23T00:00:01Z",
            "snapshot": successor,
        },
        "decision_family": "ordinary_combat",
        "surface": pre["interaction"]["content_schema"],
        "eligibility": {"status": "admitted", "passed_gates": [], "non_claims": []},
    }


def _checksums(directory: Path) -> None:
    files = sorted(
        path for path in directory.rglob("*") if path.is_file() and path.name != "checksums.sha256"
    )
    (directory / "checksums.sha256").write_text(
        "".join(f"{_sha(path)}  {path.relative_to(directory).as_posix()}\n" for path in files),
        encoding="utf-8",
    )


def _make_bundle(
    collection_root: Path,
    profile: CollectionProfile,
    campaign: CollectionCampaign,
    *,
    worker_id: str,
    session_id: str,
    records: list[dict[str, Any]],
) -> Path:
    bundle = collection_root / "sessions" / worker_id / session_id
    raw = bundle / "raw"
    raw.mkdir(parents=True)
    export = bundle / "export" / "decisions.jsonl"
    export.parent.mkdir()
    encoded_records = "".join(
        json.dumps(
            record,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
        for record in records
    )
    # The production Annotator exports deterministic UTF-8/LF bytes on every OS.
    export.write_bytes(encoded_records.encode("utf-8"))
    run_ids = sorted({record["run_id"] for record in records})
    for run_id in run_ids:
        selected = [record for record in records if record["run_id"] == run_id]
        (raw / f"{run_id}.jsonl").write_bytes(
            "".join(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
                + "\n"
                for record in selected
            ).encode("utf-8"),
        )
    _write(
        raw / "recording-manifest.json",
        {
            "schema_version": 1,
            "schema": "sts2.human-annotator/recording-manifest-1",
            "session_id": session_id,
            "created_at": "2026-08-23T00:00:00Z",
            "recorder_version": "0.1.0",
            "recorder_source_revision": profile.value["annotator"]["source_revision"],
            "platform": profile.value["platform"],
            "supported_families": list(profile.value["allowed_action_families"]),
            "non_claims": [],
        },
    )
    (raw / "invalidations.jsonl").write_text("", encoding="utf-8")
    _write(
        raw / "coverage.json",
        {
            "schema_version": 1,
            "session_id": session_id,
            "admitted_records": len(records),
            "invalidations": 0,
            "families": {"ordinary_combat": len(records)},
            "invalidations_by_reason": {},
            "updated_at": "2026-08-23T00:00:00Z",
        },
    )
    audit = {
        "schema": "sts2.human-annotator/session-bundle-audit-1",
        "status": "pass",
        "valid_records": len(records),
        "invalid_records": 0,
        "invalidations": 0,
        "errors": {},
        "non_claims": [],
    }
    _write(bundle / "audit" / "audit-report.json", audit)
    _write(bundle / "profile" / "collection-profile.json", profile.value)
    raw_sha = {path.name: _sha(path) for path in sorted(raw.iterdir())}
    export_sha = _sha(export)
    attestation = {
        "attested": True,
        "method": "explicit_owner_pack",
        "worker_id": worker_id,
        "machine_verifiable": False,
    }
    identity = {
        "schema": "sts2.human-annotator/session-bundle-1",
        "session_id": session_id,
        "collection_profile_id": profile.profile_id,
        "collection_profile_sha256": profile.sha256,
        "campaign_id": campaign.campaign_id,
        "worker_id": worker_id,
        "human_origin_attestation": attestation,
        "record_count": len(records),
        "run_ids": run_ids,
        "export_sha256": export_sha,
        "raw_file_sha256": raw_sha,
        "audit": {
            "status": "pass",
            "valid_records": len(records),
            "invalid_records": 0,
            "invalidations": 0,
        },
    }
    manifest = {
        "schema_version": 1,
        "schema": "sts2.human-annotator/session-bundle-1",
        "bundle_content_id": semantic_hash(identity),
        "session_id": session_id,
        "collection_profile_id": profile.profile_id,
        "collection_profile_sha256": profile.sha256,
        "campaign_id": campaign.campaign_id,
        "worker_id": worker_id,
        "human_origin_attestation": attestation,
        "created_at": "2026-08-23T00:00:00Z",
        "packer": {"product": "fixture", "version": "1", "source_revision": "c" * 40},
        "record_count": len(records),
        "run_ids": run_ids,
        "export_sha256": export_sha,
        "audit_status": "pass",
        "content_identity": identity,
    }
    _write(bundle / "session-bundle-manifest.json", manifest)
    _checksums(bundle)
    return bundle


def _setup(tmp_path: Path) -> tuple[CollectionProfile, CollectionCampaign, Path, Path]:
    profile = CollectionProfile.load(PROFILE_PATH)
    campaign = CollectionCampaign.load(CAMPAIGN_PATH)
    collection = tmp_path / "human-data"
    registry = collection / "registry"
    return profile, campaign, collection, registry


def _write_tokenizer(path: Path) -> None:
    tokenizer = Tokenizer(WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer.save(str(path))


def _campaign_with_target(tmp_path: Path, target: int) -> CollectionCampaign:
    value = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
    value["target_accepted_records"] = target
    path = tmp_path / f"campaign-target-{target}.json"
    _write(path, value)
    return CollectionCampaign.load(path)


def _register(
    collection: Path,
    registry: Path,
    profile: CollectionProfile,
    campaign: CollectionCampaign,
    bundle: Path,
) -> None:
    register_session_bundle(
        collection_root=collection,
        bundle_directory=bundle,
        registry_directory=registry,
        profile=profile,
        campaign=campaign,
    )


def test_two_sequence_one_sessions_build_deterministically_and_retry(tmp_path: Path) -> None:
    profile, campaign, collection, registry = _setup(tmp_path)
    for index, worker in enumerate(("human-001", "human-002"), start=1):
        session = f"session-20260823T00000{index}Z-{index:032x}"
        record = _record(
            profile,
            session_id=session,
            run_id="run-0001",
            record_id=f"record-{index:04d}",
            sequence=1,
            state_marker=f"state-{index}",
        )
        bundle = _make_bundle(
            collection, profile, campaign, worker_id=worker, session_id=session, records=[record]
        )
        _register(collection, registry, profile, campaign, bundle)
    output = tmp_path / "corpora"
    first = build_human_corpus(
        collection_root=collection,
        registry_directory=registry,
        profile=profile,
        campaign=campaign,
        output_root=output,
        schema_root=ROOT / "schemas",
        stpd_source_revision="d" * 40,
        split_salt="human-smoke-v1",
    )
    retry = build_human_corpus(
        collection_root=collection,
        registry_directory=registry,
        profile=profile,
        campaign=campaign,
        output_root=output,
        schema_root=ROOT / "schemas",
        stpd_source_revision="d" * 40,
        split_salt="human-smoke-v1",
    )
    assert first.status == "built" and retry.status == "reused"
    assert first.corpus_id == retry.corpus_id
    assert first.accepted_records == 2 and first.sessions == 2
    assert inspect_corpus_snapshot(first.snapshot_directory)["status"] == "pass"
    report = json.loads((first.snapshot_directory / "corpus-report.json").read_text())
    assert report["targeted_play"] == 0
    assert report["untargeted_play"] == 2


def test_collection_documents_match_their_machine_schemas() -> None:
    cases = (
        (PROFILE_PATH, ROOT / "schemas" / "human-collection-profile-v1.schema.json"),
        (CAMPAIGN_PATH, ROOT / "schemas" / "human-collection-campaign-v1.schema.json"),
    )
    for document_path, schema_path in cases:
        document = json.loads(document_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(document)


def test_checksum_tampering_and_profile_drift_fail_closed(tmp_path: Path) -> None:
    profile, campaign, collection, _ = _setup(tmp_path)
    record = _record(
        profile,
        session_id="session-0001",
        run_id="run-0001",
        record_id="record-0001",
        sequence=1,
        state_marker="state-1",
    )
    bundle = _make_bundle(
        collection,
        profile,
        campaign,
        worker_id="human-001",
        session_id="session-0001",
        records=[record],
    )
    (bundle / "export" / "decisions.jsonl").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(HumanCorpusError, match="checksum mismatch"):
        verify_session_bundle(bundle, profile)

    bundle = _make_bundle(
        collection,
        profile,
        campaign,
        worker_id="human-001",
        session_id="session-0002",
        records=[{**record, "session_id": "session-0002", "record_id": "record-0002"}],
    )
    drifted = copy.deepcopy(profile.value)
    drifted["game"]["main_assembly_sha256"] = "0" * 64
    drift_path = tmp_path / "drift-profile.json"
    _write(drift_path, drifted)
    with pytest.raises(HumanCorpusError, match="embedded collection profile"):
        verify_session_bundle(bundle, CollectionProfile.load(drift_path))


def test_duplicate_bundle_registration_is_idempotent_but_changed_entry_fails(
    tmp_path: Path,
) -> None:
    profile, campaign, collection, registry = _setup(tmp_path)
    record = _record(
        profile,
        session_id="session-0001",
        run_id="run-0001",
        record_id="record-0001",
        sequence=1,
        state_marker="state-1",
    )
    bundle = _make_bundle(
        collection,
        profile,
        campaign,
        worker_id="human-001",
        session_id="session-0001",
        records=[record],
    )
    _, first = register_session_bundle(
        collection_root=collection,
        bundle_directory=bundle,
        registry_directory=registry,
        profile=profile,
        campaign=campaign,
    )
    _, retry = register_session_bundle(
        collection_root=collection,
        bundle_directory=bundle,
        registry_directory=registry,
        profile=profile,
        campaign=campaign,
    )
    assert (first, retry) == ("created", "reused")
    entry_path = registry / "session-0001.json"
    changed = json.loads(entry_path.read_text())
    changed["worker_id"] = "human-002"
    _write(entry_path, changed)
    with pytest.raises(HumanCorpusError, match="immutable registry"):
        register_session_bundle(
            collection_root=collection,
            bundle_directory=bundle,
            registry_directory=registry,
            profile=profile,
            campaign=campaign,
        )


def test_duplicate_registry_file_fails_before_corpus_admission(tmp_path: Path) -> None:
    profile, campaign, collection, registry = _setup(tmp_path)
    record = _record(
        profile,
        session_id="session-0001",
        run_id="run-0001",
        record_id="record-0001",
        sequence=1,
        state_marker="state-1",
    )
    bundle = _make_bundle(
        collection,
        profile,
        campaign,
        worker_id="human-001",
        session_id="session-0001",
        records=[record],
    )
    _register(collection, registry, profile, campaign, bundle)
    shutil.copy2(registry / "session-0001.json", registry / "duplicate.json")
    with pytest.raises(HumanCorpusError, match="duplicate session ID"):
        build_human_corpus(
            collection_root=collection,
            registry_directory=registry,
            profile=profile,
            campaign=campaign,
            output_root=tmp_path / "corpora",
            schema_root=ROOT / "schemas",
            stpd_source_revision="d" * 40,
            split_salt="human-smoke-v1",
        )


def test_record_collision_fails_across_sessions(tmp_path: Path) -> None:
    profile, campaign, collection, registry = _setup(tmp_path)
    for index, worker in enumerate(("human-001", "human-002"), start=1):
        session = f"session-{index:04d}"
        record = _record(
            profile,
            session_id=session,
            run_id="run-0001",
            record_id="record-collision",
            sequence=1,
            state_marker=f"state-{index}",
        )
        bundle = _make_bundle(
            collection, profile, campaign, worker_id=worker, session_id=session, records=[record]
        )
        _register(collection, registry, profile, campaign, bundle)
    with pytest.raises(HumanCorpusError, match="record collision"):
        build_human_corpus(
            collection_root=collection,
            registry_directory=registry,
            profile=profile,
            campaign=campaign,
            output_root=tmp_path / "corpora",
            schema_root=ROOT / "schemas",
            stpd_source_revision="d" * 40,
            split_salt="human-smoke-v1",
        )


def test_whole_run_and_cross_session_duplicates_share_split(tmp_path: Path) -> None:
    profile, campaign, collection, registry = _setup(tmp_path)
    for index, worker in enumerate(("human-001", "human-002"), start=1):
        session = f"session-{index:04d}"
        records = [
            _record(
                profile,
                session_id=session,
                run_id="run-0001",
                record_id=f"record-{index}-1",
                sequence=1,
                state_marker="same-semantic-state",
            ),
            _record(
                profile,
                session_id=session,
                run_id="run-0001",
                record_id=f"record-{index}-2",
                sequence=2,
                state_marker=f"unique-{index}",
            ),
        ]
        bundle = _make_bundle(
            collection, profile, campaign, worker_id=worker, session_id=session, records=records
        )
        _register(collection, registry, profile, campaign, bundle)
    built = build_human_corpus(
        collection_root=collection,
        registry_directory=registry,
        profile=profile,
        campaign=campaign,
        output_root=tmp_path / "corpora",
        schema_root=ROOT / "schemas",
        stpd_source_revision="d" * 40,
        split_salt="human-smoke-v1",
    )
    manifest = json.loads((built.snapshot_directory / "manifest.json").read_text())
    assignments = manifest["split"]["assignments"]
    assert len(assignments) == 2
    assert len(set(assignments.values())) == 1
    report = json.loads((built.snapshot_directory / "corpus-report.json").read_text())
    assert report["deduplication"]["cross_session_semantic_duplicate_groups"] == 1
    assert report["deduplication"]["cross_split_semantic_duplicates"] == 0


def test_reordered_registry_same_corpus_and_new_session_keeps_old_snapshot(
    tmp_path: Path,
) -> None:
    profile, campaign, collection, registry = _setup(tmp_path)
    bundles = []
    for index, worker in enumerate(("human-001", "human-002"), start=1):
        session = f"session-{index:04d}"
        bundle = _make_bundle(
            collection,
            profile,
            campaign,
            worker_id=worker,
            session_id=session,
            records=[
                _record(
                    profile,
                    session_id=session,
                    run_id="run-0001",
                    record_id=f"record-{index}",
                    sequence=1,
                    state_marker=f"state-{index}",
                )
            ],
        )
        bundles.append(bundle)
        _register(collection, registry, profile, campaign, bundle)
    output = tmp_path / "corpora"
    first = build_human_corpus(
        collection_root=collection,
        registry_directory=registry,
        profile=profile,
        campaign=campaign,
        output_root=output,
        schema_root=ROOT / "schemas",
        stpd_source_revision="d" * 40,
        split_salt="human-smoke-v1",
    )
    old_checksums = (first.snapshot_directory / "checksums.sha256").read_bytes()
    reversed_registry = collection / "registry-reversed"
    reversed_registry.mkdir()
    entries = list(registry.glob("*.json"))
    for index, entry in enumerate(reversed(entries)):
        shutil.copy2(entry, reversed_registry / f"entry-{index}.json")
    reordered = build_human_corpus(
        collection_root=collection,
        registry_directory=reversed_registry,
        profile=profile,
        campaign=campaign,
        output_root=output,
        schema_root=ROOT / "schemas",
        stpd_source_revision="d" * 40,
        split_salt="human-smoke-v1",
    )
    assert reordered.corpus_id == first.corpus_id

    session = "session-0003"
    third = _make_bundle(
        collection,
        profile,
        campaign,
        worker_id="human-003",
        session_id=session,
        records=[
            _record(
                profile,
                session_id=session,
                run_id="run-0001",
                record_id="record-3",
                sequence=1,
                state_marker="state-3",
            )
        ],
    )
    _register(collection, registry, profile, campaign, third)
    expanded = build_human_corpus(
        collection_root=collection,
        registry_directory=registry,
        profile=profile,
        campaign=campaign,
        output_root=output,
        schema_root=ROOT / "schemas",
        stpd_source_revision="d" * 40,
        split_salt="human-smoke-v1",
    )
    assert expanded.corpus_id != first.corpus_id
    assert (first.snapshot_directory / "checksums.sha256").read_bytes() == old_checksums


def test_invalid_strict_session_and_smoke_threshold_fail_closed(tmp_path: Path) -> None:
    profile, campaign, collection, registry = _setup(tmp_path)
    record = _record(
        profile,
        session_id="session-0001",
        run_id="run-0001",
        record_id="record-0001",
        sequence=1,
        state_marker="state-1",
    )
    bundle = _make_bundle(
        collection,
        profile,
        campaign,
        worker_id="human-001",
        session_id="session-0001",
        records=[record],
    )
    _register(collection, registry, profile, campaign, bundle)
    built = build_human_corpus(
        collection_root=collection,
        registry_directory=registry,
        profile=profile,
        campaign=campaign,
        output_root=tmp_path / "corpora",
        schema_root=ROOT / "schemas",
        stpd_source_revision="d" * 40,
        split_salt="human-smoke-v1",
    )
    with pytest.raises(HumanCorpusError, match="token-profile-report"):
        freeze_smoke_handoff(
            snapshot_directory=built.snapshot_directory,
            output_root=tmp_path / "handoffs",
            minimum_records=1,
        )

    broken = _make_bundle(
        collection,
        profile,
        campaign,
        worker_id="human-002",
        session_id="session-0002",
        records=[
            _record(
                profile,
                session_id="session-0002",
                run_id="run-0001",
                record_id="record-0002",
                sequence=1,
                state_marker="state-2",
            )
        ],
    )
    export = broken / "export" / "decisions.jsonl"
    bad_record = json.loads(export.read_text())
    bad_record["mapping"]["status"] = "ambiguous"
    bad_record["mapping"]["match_count"] = 2
    bad_encoded = json.dumps(
        bad_record,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ) + "\n"
    export.write_bytes(bad_encoded.encode("utf-8"))
    raw_run = broken / "raw" / "run-0001.jsonl"
    raw_run.write_bytes(bad_encoded.encode("utf-8"))
    # Rebuild the attacker-controlled envelope so strict admission, not checksums, owns rejection.
    manifest_path = broken / "session-bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["export_sha256"] = _sha(export)
    manifest["content_identity"]["export_sha256"] = _sha(export)
    manifest["content_identity"]["raw_file_sha256"]["run-0001.jsonl"] = _sha(raw_run)
    manifest["bundle_content_id"] = semantic_hash(manifest["content_identity"])
    _write(manifest_path, manifest)
    _checksums(broken)
    _register(collection, registry, profile, campaign, broken)
    with pytest.raises(HumanCorpusError, match="strict single-session import failed"):
        build_human_corpus(
            collection_root=collection,
            registry_directory=registry,
            profile=profile,
            campaign=campaign,
            output_root=tmp_path / "corpora",
            schema_root=ROOT / "schemas",
            stpd_source_revision="d" * 40,
            split_salt="human-smoke-v1",
        )


def test_token_profile_and_smoke_handoff_are_frozen_and_idempotent(tmp_path: Path) -> None:
    profile, _, collection, registry = _setup(tmp_path)
    campaign = _campaign_with_target(tmp_path, 1)
    record = _record(
        profile,
        session_id="session-0001",
        run_id="run-0001",
        record_id="record-0001",
        sequence=1,
        state_marker="state-1",
    )
    bundle = _make_bundle(
        collection,
        profile,
        campaign,
        worker_id="human-001",
        session_id="session-0001",
        records=[record],
    )
    _register(collection, registry, profile, campaign, bundle)
    tokenizer_path = tmp_path / "tokenizer.json"
    _write_tokenizer(tokenizer_path)
    built = build_human_corpus(
        collection_root=collection,
        registry_directory=registry,
        profile=profile,
        campaign=campaign,
        output_root=tmp_path / "corpora",
        schema_root=ROOT / "schemas",
        stpd_source_revision="d" * 40,
        split_salt="human-smoke-v1",
        tokenizer_path=tokenizer_path,
        tokenizer_revision="fixture-tokenizer-v1",
    )
    first = freeze_smoke_handoff(
        snapshot_directory=built.snapshot_directory,
        output_root=tmp_path / "handoffs",
        minimum_records=1,
    )
    retry = freeze_smoke_handoff(
        snapshot_directory=built.snapshot_directory,
        output_root=tmp_path / "handoffs",
        minimum_records=1,
    )
    assert first == retry
    handoff = json.loads((first / "handoff.json").read_text(encoding="utf-8"))
    assert handoff["training_authorized"] is False
    assert handoff["accepted_records"] == 1


def test_smoke_handoff_cannot_lower_the_campaign_target(tmp_path: Path) -> None:
    profile, _, collection, registry = _setup(tmp_path)
    campaign = _campaign_with_target(tmp_path, 2)
    record = _record(
        profile,
        session_id="session-0001",
        run_id="run-0001",
        record_id="record-0001",
        sequence=1,
        state_marker="state-1",
    )
    bundle = _make_bundle(
        collection,
        profile,
        campaign,
        worker_id="human-001",
        session_id="session-0001",
        records=[record],
    )
    _register(collection, registry, profile, campaign, bundle)
    tokenizer_path = tmp_path / "tokenizer.json"
    _write_tokenizer(tokenizer_path)
    built = build_human_corpus(
        collection_root=collection,
        registry_directory=registry,
        profile=profile,
        campaign=campaign,
        output_root=tmp_path / "corpora",
        schema_root=ROOT / "schemas",
        stpd_source_revision="d" * 40,
        split_salt="human-smoke-v1",
        tokenizer_path=tokenizer_path,
    )
    with pytest.raises(HumanCorpusError, match="at least 2 accepted records"):
        freeze_smoke_handoff(
            snapshot_directory=built.snapshot_directory,
            output_root=tmp_path / "handoffs",
            minimum_records=1,
        )
