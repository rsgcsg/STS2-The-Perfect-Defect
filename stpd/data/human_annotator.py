"""Fail-closed import of STS2 Native UI Human Annotator evidence.

The raw recorder owns native-origin and exact BoundAction-mapping evidence. STPD
only validates that evidence, applies its existing Player Environment research
projection, and assigns research eligibility. It never reconstructs legality.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from ..canonical import semantic_hash
from ..contracts import ContractError, EnvironmentIdentity, TransitionEligibility
from ..environment.projector import ResearchProjectorV0
from ..representation import InputProfile, PolicyProvenance, ResearchState, ResearchTransition

_RECORD_SCHEMA = "sts2.human-annotator/decision-record-1"
_EXACT_MAPPING_BASIS = "reference_equality_to_frozen_host_binding"
_EXACT_MODSET_STATUS = "canary_exact_observer_modset"


class HumanRecordRejection(StrEnum):
    MALFORMED_JSON = "malformed_json"
    INVALID_SCHEMA = "invalid_schema"
    MISSING_EXACT_IDENTITY = "missing_exact_identity"
    MODSET_NOT_ADMITTED = "modset_not_admitted"
    PRE_FRAME_NOT_AUTHORITATIVE = "pre_frame_not_authoritative"
    MAPPING_NOT_EXACT_UNIQUE = "mapping_not_exact_unique"
    CHOSEN_ACTION_NOT_EXACTLY_ONCE = "chosen_action_not_exactly_once"
    SUCCESSOR_NOT_STABLE = "successor_not_stable"
    RUNTIME_IDENTITY_DRIFT = "runtime_identity_drift"
    OUTSIDE_COMBAT_SCOPE = "outside_combat_scope"
    DUPLICATE_RECORD_ID = "duplicate_record_id"
    NON_MONOTONIC_SEQUENCE = "non_monotonic_sequence"
    PROJECTION_FAILED = "projection_failed"


@dataclass(frozen=True)
class RejectedHumanRecord:
    record_ref: str
    reason: HumanRecordRejection
    detail: str


@dataclass(frozen=True)
class ImportedHumanRecord:
    transition: ResearchTransition
    record_id: str
    source_sha256: str
    annotator_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition": self.transition.to_dict(),
            "human_provenance": {
                "record_id": self.record_id,
                "source_sha256": self.source_sha256,
                "annotator_version": self.annotator_version,
                "behavior_policy_source": "human_native_ui",
            },
        }


@dataclass(frozen=True)
class HumanImportReport:
    source_path: str
    source_sha256: str
    accepted: tuple[ImportedHumanRecord, ...]
    rejected: tuple[RejectedHumanRecord, ...]

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

    @property
    def rejection_counts(self) -> Mapping[str, int]:
        return dict(sorted(Counter(item.reason.value for item in self.rejected).items()))


class _Reject(ValueError):
    def __init__(self, reason: HumanRecordRejection, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def import_human_recording(
    path: str | Path, *, provenance_uri: str | None = None
) -> HumanImportReport:
    """Import an Annotator export without correcting or defaulting evidence."""

    source = Path(path)
    source_bytes = source.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    accepted: list[ImportedHumanRecord] = []
    rejected: list[RejectedHumanRecord] = []
    step_by_root: Counter[str] = Counter()
    seen_record_ids: set[str] = set()
    previous_sequence = 0
    for line_number, line in enumerate(source_bytes.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record_ref = f"{provenance_uri or source}:line:{line_number}"
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            rejected.append(
                RejectedHumanRecord(
                    record_ref, HumanRecordRejection.MALFORMED_JSON, str(error)
                )
            )
            continue
        if not isinstance(value, Mapping):
            rejected.append(
                RejectedHumanRecord(
                    record_ref,
                    HumanRecordRejection.INVALID_SCHEMA,
                    "record must be a JSON object",
                )
            )
            continue
        try:
            session_id = _text(value, "session_id")
            run_id = _text(value, "run_id")
            record_id = _text(value, "record_id")
            sequence = _positive_int(value, "sequence")
            if record_id in seen_record_ids:
                raise _Reject(
                    HumanRecordRejection.DUPLICATE_RECORD_ID,
                    "record_id appeared more than once in the export",
                )
            if sequence <= previous_sequence:
                raise _Reject(
                    HumanRecordRejection.NON_MONOTONIC_SEQUENCE,
                    "record sequence is not strictly increasing",
                )
            root = f"{session_id}/{run_id}"
            imported = _normalize(
                cast(Mapping[str, Any], value),
                record_ref=record_ref,
                source_sha=source_sha,
                step_index=step_by_root[root],
            )
            accepted.append(imported)
            seen_record_ids.add(record_id)
            previous_sequence = sequence
            step_by_root[root] += 1
        except _Reject as error:
            rejected.append(RejectedHumanRecord(record_ref, error.reason, error.detail))
        except (ContractError, KeyError, TypeError, ValueError) as error:
            rejected.append(
                RejectedHumanRecord(
                    record_ref, HumanRecordRejection.PROJECTION_FAILED, str(error)
                )
            )
    return HumanImportReport(str(source), source_sha, tuple(accepted), tuple(rejected))


def _normalize(
    record: Mapping[str, Any],
    *,
    record_ref: str,
    source_sha: str,
    step_index: int,
) -> ImportedHumanRecord:
    if record.get("schema_version") != 1 or record.get("schema") != _RECORD_SCHEMA:
        raise _Reject(HumanRecordRejection.INVALID_SCHEMA, "unsupported recorder schema")
    eligibility = _mapping(record, "eligibility")
    if eligibility.get("status") != "admitted":
        raise _Reject(HumanRecordRejection.INVALID_SCHEMA, "record is not admitted")
    environment_raw = _mapping(record, "environment")
    game = _mapping(environment_raw, "game")
    connector = _mapping(environment_raw, "connector")
    annotator = _mapping(environment_raw, "annotator")
    _validate_exact_artifact(connector, "connector")
    _validate_exact_artifact(annotator, "annotator")
    _sha256(game, "main_assembly_sha256")
    _uuid(game, "main_assembly_module_version_id")
    _sha256(environment_raw, "modset_fingerprint")
    if environment_raw.get("modset_status") != _EXACT_MODSET_STATUS:
        raise _Reject(
            HumanRecordRejection.MODSET_NOT_ADMITTED,
            "record was not captured under the exact observer Modset canary",
        )

    pre = _mapping(record, "pre")
    snapshot = _mapping(pre, "snapshot")
    _validate_authoritative_snapshot(snapshot)
    interaction = _mapping(snapshot, "interaction")
    session = _mapping(snapshot, "session")
    if (
        _text(pre, "snapshot_id") != _text(snapshot, "snapshot_id")
        or _text(pre, "interaction_id") != _text(interaction, "interaction_id")
        or _text(pre, "interaction_kind") != _text(interaction, "kind")
        or _text(pre, "surface_schema") != _text(interaction, "content_schema")
        or _text(environment_raw, "player_environment_protocol")
        != _text(snapshot, "protocol_version")
        or _text(environment_raw, "runtime_instance_id")
        != _text(session, "runtime_instance_id")
        or _text(environment_raw, "environment_fingerprint")
        != _text(session, "environment_fingerprint")
    ):
        raise _Reject(
            HumanRecordRejection.PRE_FRAME_NOT_AUTHORITATIVE,
            "pre-frame envelope does not match its nested snapshot or environment",
        )
    catalog = _mapping(snapshot, "bound_actions")
    actions_raw = catalog.get("actions")
    if not isinstance(actions_raw, Sequence) or isinstance(actions_raw, (str, bytes)):
        raise _Reject(
            HumanRecordRejection.PRE_FRAME_NOT_AUTHORITATIVE,
            "pre-frame actions are not a sequence",
        )
    if (
        pre.get("catalog_count") != len(actions_raw)
        or catalog.get("materialized_count") != len(actions_raw)
        or len(actions_raw) == 0
        or _text(pre, "catalog_digest") != _ordered_json_sha256(catalog)
    ):
        raise _Reject(
            HumanRecordRejection.PRE_FRAME_NOT_AUTHORITATIVE,
            "frozen catalog count does not match its action list",
        )

    mapping = _mapping(record, "mapping")
    if (
        mapping.get("status") != "exact_unique"
        or mapping.get("match_count") != 1
        or mapping.get("basis") != _EXACT_MAPPING_BASIS
    ):
        raise _Reject(
            HumanRecordRejection.MAPPING_NOT_EXACT_UNIQUE,
            "native witness is not an exact unique frozen-binding match",
        )
    chosen_raw = _mapping(record, "action")
    chosen_bound_id = _text(chosen_raw, "bound_action_id")
    matches = [
        action
        for action in actions_raw
        if isinstance(action, Mapping) and action.get("bound_action_id") == chosen_bound_id
    ]
    if len(matches) != 1 or not _same_public_action(matches[0], chosen_raw):
        raise _Reject(
            HumanRecordRejection.CHOSEN_ACTION_NOT_EXACTLY_ONCE,
            "recorded action does not match exactly one frozen catalog entry",
        )
    _validate_native_witness(record, chosen_raw)

    successor_evidence = _mapping(record, "successor")
    successor_snapshot = _mapping(successor_evidence, "snapshot")
    _validate_authoritative_snapshot(successor_snapshot)
    successor_interaction = _mapping(successor_snapshot, "interaction")
    if (
        successor_evidence.get("status") != "interactive"
        or successor_snapshot.get("status") != "interactive"
        or successor_snapshot.get("snapshot_id") == snapshot.get("snapshot_id")
        or _text(successor_evidence, "snapshot_id")
        != _text(successor_snapshot, "snapshot_id")
        or _text(successor_evidence, "interaction_id")
        != _text(successor_interaction, "interaction_id")
        or _text(successor_evidence, "interaction_kind")
        != _text(successor_interaction, "kind")
    ):
        raise _Reject(
            HumanRecordRejection.SUCCESSOR_NOT_STABLE,
            "successor must be a different stable interactive snapshot",
        )
    _validate_runtime_continuity(snapshot, successor_snapshot)

    if not _is_combat(interaction):
        raise _Reject(
            HumanRecordRejection.OUTSIDE_COMBAT_SCOPE,
            "STPD v0 imports only Combat human decisions",
        )
    projector = ResearchProjectorV0()
    game_version = _text(game, "version")
    game_commit = _text(game, "commit")
    record_id = _text(record, "record_id")
    projected = projector.project(
        snapshot,
        {},
        game_version=game_version,
        game_commit=game_commit,
        mutation_request_prefix=f"human-evidence-{record_id}",
    )
    chosen = next(
        (
            action
            for action, envelope in zip(projected.actions, projected.envelopes, strict=True)
            if envelope.bound_action_id == chosen_bound_id
        ),
        None,
    )
    if chosen is None:
        raise _Reject(
            HumanRecordRejection.CHOSEN_ACTION_NOT_EXACTLY_ONCE,
            "research projection did not preserve the chosen BoundAction",
        )

    successor_state: ResearchState | None = None
    scope_exit = True
    if _is_combat(successor_interaction):
        successor_state = projector.project_state(
            successor_snapshot,
            {},
            game_version=game_version,
            game_commit=game_commit,
        )
        scope_exit = False

    exact_environment = EnvironmentIdentity(
        game_version=game_version,
        game_commit=game_commit,
        game_artifact_sha256=_text(game, "main_assembly_sha256"),
        game_artifact_mvid=_text(game, "main_assembly_module_version_id"),
        host_kind="reference_ui_human",
        host_source_revision=_text(connector, "source_revision"),
        host_source_digest_sha256=_text(connector, "source_digest_sha256"),
        host_artifact_sha256=_text(connector, "sha256"),
        host_artifact_mvid=_text(connector, "module_version_id"),
        player_environment_protocol=_text(environment_raw, "player_environment_protocol"),
        player_environment_implementation="sts2_connector_live_host",
        player_environment_revision=_text(connector, "source_revision"),
        player_environment_digest_sha256=_text(connector, "source_digest_sha256"),
        information_policy_id=_text(_mapping(snapshot, "information_policy"), "id"),
    )
    exact_environment.validate()
    session_id = _text(record, "session_id")
    run_id = _text(record, "run_id")
    root = f"{session_id}/{run_id}"
    policy = PolicyProvenance(
        source="human_native_ui",
        version=_text(annotator, "version"),
        config_hash=semantic_hash(
            {
                "annotator_source": annotator.get("source_revision"),
                "annotator_artifact": annotator.get("sha256"),
                "mapping": _EXACT_MAPPING_BASIS,
                "modset": environment_raw.get("modset_fingerprint"),
            }
        ),
        teacher_confidence=None,
    )
    transition = ResearchTransition(
        transition_id=f"human:{record_id}",
        episode_id=f"human:{root}",
        step_index=step_index,
        seed=f"human-root:{root}",
        environment=exact_environment,
        policy=policy,
        decision_mode="combat",
        surface=projected.state.surface,
        input_profile=InputProfile.STANDARD,
        eligibility=TransitionEligibility(
            rank=True,
            rank_mode="full_listwise",
            transition=True,
            return_=False,
            legal_action_completeness="complete",
            reason_codes=("human_native_ui_exact_mapping", "game_seed_not_player_exposed"),
        ),
        state=projected.state,
        legal_actions=projected.actions,
        chosen_action=chosen,
        successor=successor_state,
        terminal=False,
        scope_exit=scope_exit,
        outcome=None,
        raw_ref=record_ref,
    )
    transition.validate()
    return ImportedHumanRecord(
        transition,
        record_id,
        source_sha,
        _text(annotator, "version"),
    )


def _validate_authoritative_snapshot(snapshot: Mapping[str, Any]) -> None:
    completeness = _mapping(snapshot, "completeness")
    catalog = _mapping(snapshot, "bound_actions")
    if (
        snapshot.get("status") != "interactive"
        or completeness.get("status") != "complete"
        or catalog.get("status") != "complete"
    ):
        raise _Reject(
            HumanRecordRejection.PRE_FRAME_NOT_AUTHORITATIVE,
            "snapshot is not complete and interactive",
        )


def _validate_runtime_continuity(
    pre: Mapping[str, Any], successor: Mapping[str, Any]
) -> None:
    if _mapping(pre, "session") != _mapping(successor, "session"):
        raise _Reject(
            HumanRecordRejection.RUNTIME_IDENTITY_DRIFT,
            "pre and successor session identities differ",
        )


def _is_combat(interaction: Mapping[str, Any]) -> bool:
    content = interaction.get("content")
    context = content.get("context") if isinstance(content, Mapping) else None
    return isinstance(context, Mapping) and context.get("kind") == "combat"


def _same_public_action(catalog: Mapping[str, Any], recorded: Mapping[str, Any]) -> bool:
    catalog_arguments = {
        str(item.get("role")): str(item.get("referent_id"))
        for item in catalog.get("arguments", ())
        if isinstance(item, Mapping)
    }
    recorded_arguments = recorded.get("arguments")
    return (
        catalog.get("bound_action_id") == recorded.get("bound_action_id")
        and catalog.get("verb") == recorded.get("verb")
        and catalog.get("subject_referent_id") == recorded.get("subject_referent_id")
        and isinstance(recorded_arguments, Mapping)
        and catalog_arguments == dict(recorded_arguments)
    )


def _validate_native_witness(
    record: Mapping[str, Any], chosen: Mapping[str, Any]
) -> None:
    witness = _mapping(record, "native_witness")
    _text(witness, "origin")
    _text(witness, "native_action_type")
    _text(witness, "accepted_at")
    subject = chosen.get("subject_referent_id")
    subject_witness = witness.get("subject_witness_id")
    if (subject is None) != (subject_witness is None):
        raise _Reject(
            HumanRecordRejection.INVALID_SCHEMA,
            "native subject witness shape differs from the chosen action",
        )
    if subject is not None and not isinstance(subject_witness, str):
        raise _Reject(HumanRecordRejection.INVALID_SCHEMA, "native subject witness is missing")
    argument_witnesses = _mapping(witness, "argument_witness_ids")
    chosen_arguments = _mapping(chosen, "arguments")
    if set(argument_witnesses) != set(chosen_arguments) or not all(
        isinstance(value, str) and value for value in argument_witnesses.values()
    ):
        raise _Reject(
            HumanRecordRejection.INVALID_SCHEMA,
            "native argument witnesses do not match the chosen action roles",
        )


def _validate_exact_artifact(value: Mapping[str, Any], name: str) -> None:
    revision = _text(value, "source_revision")
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise _Reject(
            HumanRecordRejection.MISSING_EXACT_IDENTITY,
            f"{name} source revision is not an exact Git SHA",
        )
    _sha256(value, "source_digest_sha256")
    _sha256(value, "sha256")
    _uuid(value, "module_version_id")


def _sha256(value: Mapping[str, Any], key: str) -> str:
    text = _text(value, key)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text.lower()):
        raise _Reject(
            HumanRecordRejection.MISSING_EXACT_IDENTITY,
            f"{key} is not a SHA-256 digest",
        )
    return text


def _uuid(value: Mapping[str, Any], key: str) -> str:
    text = _text(value, key)
    try:
        uuid.UUID(text)
    except ValueError as error:
        raise _Reject(
            HumanRecordRejection.MISSING_EXACT_IDENTITY,
            f"{key} is not a UUID",
        ) from error
    return text


def _ordered_json_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _positive_int(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
        raise _Reject(HumanRecordRejection.INVALID_SCHEMA, f"invalid positive integer: {key}")
    return item


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise _Reject(HumanRecordRejection.INVALID_SCHEMA, f"missing object: {key}")
    return cast(Mapping[str, Any], item)


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise _Reject(HumanRecordRejection.INVALID_SCHEMA, f"missing text: {key}")
    return item
