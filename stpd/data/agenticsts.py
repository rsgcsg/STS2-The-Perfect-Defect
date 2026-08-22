"""Fail-closed importer for AgenticSTS decision records.

AgenticSTS is historical source data, not a second STPD domain model.  The
importer accepts a small source envelope around the already extracted fields
needed by :class:`stpd.representation.ResearchTransition`.  It never derives
legality from prompts, array positions, or a current Headless installation.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, TextIO, cast

from ..contracts import EnvironmentIdentity, TransitionEligibility
from ..representation import (
    DecisionFamily,
    InputProfile,
    PolicyProvenance,
    ResearchAction,
    ResearchState,
    ResearchTransition,
)


class RejectionCode(StrEnum):
    """Stable machine-readable reasons for excluding one source record."""

    MALFORMED_JSON = "malformed_json"
    INVALID_RECORD = "invalid_record"
    MISSING_PROVENANCE = "missing_provenance"
    MISSING_LICENSE = "missing_license"
    UNKNOWN_LICENSE = "unknown_license"
    NON_COMBAT_RECORD = "non_combat_record"
    MISSING_LEGAL_ACTION_CATALOG = "missing_legal_action_catalog"
    INCOMPLETE_LEGAL_ACTION_CATALOG = "incomplete_legal_action_catalog"
    AMBIGUOUS_ACTION_MAPPING = "ambiguous_action_mapping"
    CHOSEN_ACTION_NOT_IN_CATALOG = "chosen_action_not_in_catalog"
    MISSING_SUCCESSOR = "missing_successor"
    UNSTABLE_SUCCESSOR = "unstable_successor"
    INVALID_TRANSITION_CONTRACT = "invalid_transition_contract"


class _RejectedRecord(ValueError):
    def __init__(
        self,
        code: RejectionCode,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True)
class SourceProvenance:
    """License and source identity retained beside a normalized transition."""

    dataset: str
    revision: str
    license: str
    source_url: str
    record_ref: str
    license_url: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.metadata)
        result.update(
            {
                "dataset": self.dataset,
                "revision": self.revision,
                "license": self.license,
                "source_url": self.source_url,
                "record_ref": self.record_ref,
            }
        )
        if self.license_url is not None:
            result["license_url"] = self.license_url
        return result


@dataclass(frozen=True)
class RejectedRecord:
    """A source record that was quarantined without being normalized."""

    record_ref: str
    reason_code: RejectionCode
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_ref": self.record_ref,
            "reason_code": self.reason_code.value,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class NormalizedAgenticSTSRecord:
    """A canonical transition plus its non-model provenance sidecar."""

    transition: ResearchTransition
    provenance: SourceProvenance

    @property
    def normalized_transition(self) -> dict[str, Any]:
        """Return the exact mapping accepted by the existing transition layer."""

        return self.transition.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition": self.normalized_transition,
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True)
class ImportReport:
    """Accepted and rejected records from one immutable source read."""

    source_path: str
    accepted: tuple[NormalizedAgenticSTSRecord, ...]
    rejected: tuple[RejectedRecord, ...]

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "accepted": [record.to_dict() for record in self.accepted],
            "rejected": [record.to_dict() for record in self.rejected],
        }


@dataclass(frozen=True)
class _RawRecord:
    payload: Mapping[str, Any]
    record_ref: str
    source: Mapping[str, Any] | None


_LICENSE_ALIASES = {
    "CC-BY-4.0": "CC-BY-4.0",
    "CC-BY-4-0": "CC-BY-4.0",
    "CC-BY 4.0": "CC-BY-4.0",
    "CC BY 4.0": "CC-BY-4.0",
}


def import_agenticsts(
    path: str | Path,
    *,
    source_metadata: Mapping[str, Any] | None = None,
) -> ImportReport:
    """Import JSON, JSONL, or gzipped JSONL AgenticSTS records.

    A document may contain a top-level ``source``/``provenance`` mapping and
    either one record or ``{"records": [...]}``.  A JSONL line may carry its
    own source mapping.  ``source_metadata`` is an explicit file-level
    fallback for callers that keep the license manifest outside the raw file.
    Missing or unknown license metadata is always a rejection.
    """

    source_path = Path(path)
    raw_records, read_rejections = _read_records(source_path, source_metadata)
    accepted: list[NormalizedAgenticSTSRecord] = []
    rejected = list(read_rejections)

    for raw in raw_records:
        try:
            accepted.append(_normalize_record(raw))
        except _RejectedRecord as error:
            rejected.append(
                RejectedRecord(
                    record_ref=raw.record_ref,
                    reason_code=error.code,
                    message=error.message,
                    details=error.details,
                )
            )
        except Exception as error:  # Keep a bad external row from aborting the import.
            rejected.append(
                RejectedRecord(
                    record_ref=raw.record_ref,
                    reason_code=RejectionCode.INVALID_TRANSITION_CONTRACT,
                    message="unexpected transition validation failure",
                    details={"error": str(error)},
                )
            )

    return ImportReport(str(source_path), tuple(accepted), tuple(rejected))


def _read_records(
    path: Path,
    source_metadata: Mapping[str, Any] | None,
) -> tuple[list[_RawRecord], list[RejectedRecord]]:
    content_suffix = path.with_suffix("").suffix if path.suffix == ".gz" else path.suffix

    if content_suffix == ".json":
        try:
            with _open_text(path) as handle:
                document = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            return [], [
                RejectedRecord(
                    record_ref=f"{path}:document",
                    reason_code=RejectionCode.MALFORMED_JSON,
                    message="could not parse JSON document",
                    details={"error": str(error)},
                )
            ]
        return _records_from_document(document, str(path), source_metadata)

    records: list[_RawRecord] = []
    rejected: list[RejectedRecord] = []
    try:
        with _open_text(path) as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record_ref = f"{path}:line:{line_number}"
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    rejected.append(
                        RejectedRecord(
                            record_ref=record_ref,
                            reason_code=RejectionCode.MALFORMED_JSON,
                            message="could not parse JSONL record",
                            details={"error": str(error)},
                        )
                    )
                    continue
                if not isinstance(value, Mapping):
                    rejected.append(
                        RejectedRecord(
                            record_ref=record_ref,
                            reason_code=RejectionCode.INVALID_RECORD,
                            message="JSONL record must be an object",
                        )
                    )
                    continue
                records.append(
                    _RawRecord(cast(Mapping[str, Any], value), record_ref, source_metadata)
                )
    except OSError as error:
        rejected.append(
            RejectedRecord(
                record_ref=str(path),
                reason_code=RejectionCode.MALFORMED_JSON,
                message="could not read JSONL source",
                details={"error": str(error)},
            )
        )
    return records, rejected


@contextmanager
def _open_text(path: Path) -> Iterator[TextIO]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            yield handle
        return
    with path.open("rt", encoding="utf-8") as handle:
        yield handle


def _records_from_document(
    document: Any,
    document_ref: str,
    source_metadata: Mapping[str, Any] | None,
) -> tuple[list[_RawRecord], list[RejectedRecord]]:
    if isinstance(document, Mapping) and isinstance(document.get("records"), list):
        try:
            envelope_source = _optional_mapping(
                document.get("source", document.get("provenance")), document_ref
            )
        except _RejectedRecord as error:
            return [], [
                RejectedRecord(
                    record_ref=document_ref,
                    reason_code=error.code,
                    message=error.message,
                    details=error.details,
                )
            ]
        records: list[_RawRecord] = []
        rejected: list[RejectedRecord] = []
        for index, value in enumerate(document["records"]):
            record_ref = f"{document_ref}:record:{index}"
            if not isinstance(value, Mapping):
                rejected.append(
                    RejectedRecord(
                        record_ref=record_ref,
                        reason_code=RejectionCode.INVALID_RECORD,
                        message="records entries must be objects",
                    )
                )
                continue
            records.append(
                _RawRecord(
                    cast(Mapping[str, Any], value),
                    record_ref,
                    envelope_source or source_metadata,
                )
            )
        return records, rejected

    if isinstance(document, list):
        records = []
        rejected = []
        for index, value in enumerate(document):
            record_ref = f"{document_ref}:record:{index}"
            if not isinstance(value, Mapping):
                rejected.append(
                    RejectedRecord(
                        record_ref=record_ref,
                        reason_code=RejectionCode.INVALID_RECORD,
                        message="JSON array entries must be objects",
                    )
                )
                continue
            records.append(_RawRecord(cast(Mapping[str, Any], value), record_ref, source_metadata))
        return records, rejected

    if isinstance(document, Mapping):
        try:
            source = _optional_mapping(
                document.get("source", document.get("provenance")), document_ref
            )
        except _RejectedRecord as error:
            return [], [
                RejectedRecord(
                    record_ref=document_ref,
                    reason_code=error.code,
                    message=error.message,
                    details=error.details,
                )
            ]
        return [
            _RawRecord(cast(Mapping[str, Any], document), document_ref, source or source_metadata)
        ], []

    return [], [
        RejectedRecord(
            record_ref=document_ref,
            reason_code=RejectionCode.INVALID_RECORD,
            message="JSON document must be an object or array of objects",
        )
    ]


def _normalize_record(raw: _RawRecord) -> NormalizedAgenticSTSRecord:
    record = raw.payload
    provenance = _parse_provenance(
        record.get("source", record.get("provenance")), raw.source, raw.record_ref
    )
    transition_data = record.get("transition", record)
    if not isinstance(transition_data, Mapping):
        raise _RejectedRecord(
            RejectionCode.INVALID_RECORD,
            "transition must be an object",
        )
    transition = cast(Mapping[str, Any], transition_data)

    if transition.get("decision_mode") != "combat":
        raise _RejectedRecord(
            RejectionCode.NON_COMBAT_RECORD,
            "AgenticSTS importer only admits combat decisions",
            {"decision_mode": transition.get("decision_mode")},
        )

    legal_actions_value = transition.get("legal_actions")
    if (
        not isinstance(legal_actions_value, Sequence)
        or isinstance(legal_actions_value, (str, bytes))
        or not legal_actions_value
    ):
        raise _RejectedRecord(
            RejectionCode.MISSING_LEGAL_ACTION_CATALOG,
            "record has no explicit non-empty legal action catalog",
        )
    completeness = _legal_action_completeness(transition)
    if completeness != "complete":
        raise _RejectedRecord(
            RejectionCode.INCOMPLETE_LEGAL_ACTION_CATALOG,
            "record does not prove a complete legal action catalog",
            {"legal_action_completeness": completeness},
        )

    legal_actions = tuple(_action_from_mapping(value) for value in legal_actions_value)
    action_keys = [action.action_key for action in legal_actions]
    if len(action_keys) != len(set(action_keys)):
        raise _RejectedRecord(
            RejectionCode.AMBIGUOUS_ACTION_MAPPING,
            "legal action catalog contains duplicate action keys",
        )
    chosen = _resolve_chosen_action(transition.get("chosen_action"), legal_actions)

    successor = transition.get("successor")
    terminal = transition.get("terminal")
    scope_exit = transition.get("scope_exit")
    if not isinstance(terminal, bool) or not isinstance(scope_exit, bool):
        raise _RejectedRecord(
            RejectionCode.INVALID_TRANSITION_CONTRACT,
            "terminal and scope_exit must be booleans",
        )
    if successor is None and not terminal and not scope_exit:
        raise _RejectedRecord(
            RejectionCode.MISSING_SUCCESSOR,
            "non-terminal in-scope record has no successor",
        )
    if successor is not None:
        if not isinstance(successor, Mapping):
            raise _RejectedRecord(
                RejectionCode.INVALID_TRANSITION_CONTRACT,
                "successor must be an object or null",
            )
        stable = transition.get("successor_stable")
        if stable is not True:
            raise _RejectedRecord(
                RejectionCode.UNSTABLE_SUCCESSOR,
                "successor is present without explicit stable evidence",
                {"successor_stable": stable},
            )

    try:
        research_transition = _build_transition(transition, legal_actions, chosen)
        research_transition.validate()
    except Exception as error:
        raise _RejectedRecord(
            RejectionCode.INVALID_TRANSITION_CONTRACT,
            "record does not satisfy ResearchTransition v0",
            {"error": str(error)},
        ) from error

    return NormalizedAgenticSTSRecord(research_transition, provenance)


def _parse_provenance(
    record_source: Any,
    fallback_source: Mapping[str, Any] | None,
    record_ref: str,
) -> SourceProvenance:
    if record_source is not None:
        source = _optional_mapping(record_source, record_ref)
    else:
        source = fallback_source
    if source is None:
        raise _RejectedRecord(
            RejectionCode.MISSING_PROVENANCE,
            "record has no source/provenance envelope",
        )

    license_value = source.get("license")
    if not isinstance(license_value, str) or not license_value.strip():
        raise _RejectedRecord(
            RejectionCode.MISSING_LICENSE,
            "source provenance must declare a license",
        )
    normalized_license = _LICENSE_ALIASES.get(license_value.strip().upper())
    if normalized_license is None:
        raise _RejectedRecord(
            RejectionCode.UNKNOWN_LICENSE,
            "source license is not an admitted AgenticSTS license",
            {"license": license_value},
        )

    dataset = _required_text(source, "dataset", RejectionCode.MISSING_PROVENANCE)
    revision = _required_text(
        source,
        "revision",
        RejectionCode.MISSING_PROVENANCE,
        aliases=("dataset_revision",),
    )
    source_url = _required_text(
        source,
        "source_url",
        RejectionCode.MISSING_PROVENANCE,
        aliases=("url",),
    )
    source_record_ref = _required_text(
        source,
        "record_ref",
        RejectionCode.MISSING_PROVENANCE,
        default=record_ref,
        aliases=("raw_ref",),
    )
    license_url = source.get("license_url")
    if license_url is not None and (not isinstance(license_url, str) or not license_url.strip()):
        raise _RejectedRecord(
            RejectionCode.MISSING_PROVENANCE,
            "license_url must be non-empty when present",
        )
    required = {
        "dataset",
        "revision",
        "dataset_revision",
        "license",
        "source_url",
        "url",
        "record_ref",
        "raw_ref",
        "license_url",
    }
    metadata = {key: value for key, value in source.items() if key not in required}
    return SourceProvenance(
        dataset=dataset,
        revision=revision,
        license=normalized_license,
        source_url=source_url,
        record_ref=source_record_ref,
        license_url=license_url,
        metadata=metadata,
    )


def _legal_action_completeness(transition: Mapping[str, Any]) -> Any:
    eligibility = transition.get("eligibility")
    if not isinstance(eligibility, Mapping):
        return None
    return eligibility.get("legal_action_completeness")


def _resolve_chosen_action(
    chosen_value: Any,
    legal_actions: tuple[ResearchAction, ...],
) -> ResearchAction:
    if isinstance(chosen_value, str):
        matches = [action for action in legal_actions if action.action_key == chosen_value]
    elif isinstance(chosen_value, Mapping):
        chosen = cast(Mapping[str, Any], chosen_value)
        action_key = chosen.get("action_key")
        if isinstance(action_key, str) and action_key.strip():
            matches = [action for action in legal_actions if action.action_key == action_key]
        else:
            fingerprint = _action_fingerprint(chosen)
            matches = [
                action
                for action in legal_actions
                if _action_fingerprint(action.to_dict()) == fingerprint
            ]
    else:
        raise _RejectedRecord(
            RejectionCode.CHOSEN_ACTION_NOT_IN_CATALOG,
            "chosen_action must identify one catalog action",
        )

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise _RejectedRecord(
            RejectionCode.AMBIGUOUS_ACTION_MAPPING,
            "chosen_action maps to multiple catalog actions",
        )
    raise _RejectedRecord(
        RejectionCode.CHOSEN_ACTION_NOT_IN_CATALOG,
        "chosen_action does not map to the legal action catalog",
    )


def _action_fingerprint(action: Mapping[str, Any]) -> str:
    comparable = {
        "kind": action.get("kind"),
        "subject": action.get("subject"),
        "arguments": action.get("arguments", []),
        "visible_cost": action.get("visible_cost"),
        "visible_effect": action.get("visible_effect"),
    }
    return json.dumps(comparable, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _action_from_mapping(value: Any) -> ResearchAction:
    if not isinstance(value, Mapping):
        raise _RejectedRecord(
            RejectionCode.INVALID_TRANSITION_CONTRACT,
            "each legal action must be an object",
        )
    action = cast(Mapping[str, Any], value)
    action_key = action.get("action_key")
    kind = action.get("kind")
    if (
        not isinstance(action_key, str)
        or not action_key.strip()
        or not isinstance(kind, str)
        or not kind.strip()
    ):
        raise _RejectedRecord(
            RejectionCode.INVALID_TRANSITION_CONTRACT,
            "each legal action needs action_key and kind",
        )
    subject = action.get("subject")
    if subject is not None and not isinstance(subject, Mapping):
        raise _RejectedRecord(
            RejectionCode.INVALID_TRANSITION_CONTRACT,
            "action.subject must be an object or null",
        )
    arguments = action.get("arguments", ())
    if not isinstance(arguments, Sequence) or isinstance(arguments, (str, bytes)):
        raise _RejectedRecord(
            RejectionCode.INVALID_TRANSITION_CONTRACT,
            "action.arguments must be a sequence",
        )
    if any(not isinstance(argument, Mapping) for argument in arguments):
        raise _RejectedRecord(
            RejectionCode.INVALID_TRANSITION_CONTRACT,
            "action.arguments entries must be objects",
        )
    return ResearchAction(
        action_key=action_key,
        kind=kind,
        subject=cast(Mapping[str, Any] | None, subject),
        arguments=tuple(cast(Mapping[str, Any], argument) for argument in arguments),
        visible_cost=cast(str | int | float | None, action.get("visible_cost")),
        visible_effect=cast(str | None, action.get("visible_effect")),
    )


def _build_transition(
    data: Mapping[str, Any],
    legal_actions: tuple[ResearchAction, ...],
    chosen: ResearchAction,
) -> ResearchTransition:
    state_value = data.get("state")
    if not isinstance(state_value, Mapping):
        raise ValueError("state must be an object")
    state = _state_from_mapping(cast(Mapping[str, Any], state_value))

    successor_value = data.get("successor")
    successor = None
    if successor_value is not None:
        if not isinstance(successor_value, Mapping):
            raise ValueError("successor must be an object or null")
        successor = _state_from_mapping(cast(Mapping[str, Any], successor_value))

    environment_value = data.get("environment")
    policy_value = data.get("policy")
    eligibility_value = data.get("eligibility")
    if not isinstance(environment_value, Mapping):
        raise ValueError("environment must be an object; historical identity is not inferred")
    if not isinstance(policy_value, Mapping):
        raise ValueError("policy must be an object")
    if not isinstance(eligibility_value, Mapping):
        raise ValueError("eligibility must be an object")
    environment = EnvironmentIdentity(**_environment_fields(environment_value))
    policy = PolicyProvenance(**_policy_fields(policy_value))
    eligibility = TransitionEligibility(**_eligibility_fields(eligibility_value))
    input_profile = InputProfile(str(data.get("input_profile")))
    return ResearchTransition(
        transition_id=_text(data, "transition_id"),
        episode_id=_text(data, "episode_id"),
        step_index=_integer(data, "step_index"),
        seed=_text(data, "seed"),
        environment=environment,
        policy=policy,
        decision_mode=_text(data, "decision_mode"),
        surface=_text(data, "surface"),
        input_profile=input_profile,
        eligibility=eligibility,
        state=state,
        legal_actions=legal_actions,
        chosen_action=chosen,
        successor=successor,
        terminal=bool(data["terminal"]),
        scope_exit=bool(data["scope_exit"]),
        outcome=cast(Mapping[str, Any] | None, data.get("outcome")),
        raw_ref=_text(data, "raw_ref"),
    )


def _state_from_mapping(data: Mapping[str, Any]) -> ResearchState:
    facts = data.get("facts")
    reads = data.get("reads", {})
    if not isinstance(facts, Mapping) or not isinstance(reads, Mapping):
        raise ValueError("state.facts and state.reads must be objects")
    return ResearchState(
        information_policy_id=_text(data, "information_policy_id"),
        game_version=_text(data, "game_version"),
        game_commit=_text(data, "game_commit"),
        decision_mode=_text(data, "decision_mode"),
        decision_family=DecisionFamily(_text(data, "decision_family")),
        surface=_text(data, "surface"),
        facts=cast(Mapping[str, Any], facts),
        reads=cast(Mapping[str, Any], reads),
    )


def _environment_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "game_version",
        "game_commit",
        "host_kind",
        "host_source_revision",
        "host_artifact_sha256",
        "connector_version",
        "connector_source_revision",
        "connector_artifact_sha256",
        "pe_protocol",
        "information_policy_id",
    )
    return {field: _text(data, field) for field in fields}


def _policy_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source": _text(data, "source"),
        "version": _text(data, "version"),
        "config_hash": _text(data, "config_hash"),
        "teacher_confidence": data.get("teacher_confidence"),
    }


def _eligibility_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    reason_codes = data.get("reason_codes", ())
    if not isinstance(reason_codes, Sequence) or isinstance(reason_codes, (str, bytes)):
        raise ValueError("eligibility.reason_codes must be a sequence")
    rank_mode = data.get("rank_mode")
    if rank_mode not in {"full_listwise", "partial_pairwise", "chosen_only", "none"}:
        raise ValueError("eligibility.rank_mode is not recognized")
    completeness = data.get("legal_action_completeness")
    if completeness not in {"complete", "partial", "unknown"}:
        raise ValueError("eligibility.legal_action_completeness is not recognized")
    return {
        "rank": _boolean(data, "rank"),
        "rank_mode": rank_mode,
        "transition": _boolean(data, "transition"),
        "return_": _boolean(data, "return"),
        "legal_action_completeness": completeness,
        "reason_codes": tuple(str(code) for code in reason_codes),
    }


def _boolean(data: Mapping[str, Any], name: str) -> bool:
    value = data.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _optional_mapping(value: Any, record_ref: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _RejectedRecord(
            RejectionCode.INVALID_RECORD,
            "source/provenance must be an object",
            {"record_ref": record_ref},
        )
    return cast(Mapping[str, Any], value)


def _required_text(
    data: Mapping[str, Any],
    name: str,
    code: RejectionCode,
    *,
    default: str | None = None,
    aliases: tuple[str, ...] = (),
) -> str:
    value = data.get(name)
    if value is None:
        for alias in aliases:
            value = data.get(alias)
            if value is not None:
                break
    if value is None:
        value = default
    if not isinstance(value, str) or not value.strip():
        raise _RejectedRecord(code, f"source provenance needs {name}")
    return value.strip()


def _text(data: Mapping[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _integer(data: Mapping[str, Any], name: str) -> int:
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value
