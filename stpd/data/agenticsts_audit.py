"""Deterministic evidence audit for the pinned raw AgenticSTS trajectory subset.

The audit deliberately does not convert raw events into ResearchTransition objects. It
counts evidence that is explicitly present and applies the current fail-closed admission
requirements without inferring legality, game identity, seeds, or successors from game
rules or a current installation.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from ..canonical import semantic_hash

PIN_SCHEMA = "stpd/agenticsts-source-pin-v0"
AUDIT_SCHEMA = "stpd/agenticsts-raw-audit-v0"
COMBAT_STATE_TYPES = frozenset({"monster", "elite", "boss"})
CATALOG_KEYS = frozenset(
    {"legal_actions", "available_actions", "action_catalog", "bound_actions"}
)
ENVIRONMENT_FIELDS = frozenset(
    {
        "game_version",
        "game_commit",
        "game_artifact_sha256",
        "game_artifact_mvid",
        "host_kind",
        "host_source_revision",
        "host_source_digest_sha256",
        "host_artifact_sha256",
        "host_artifact_mvid",
        "player_environment_protocol",
        "player_environment_implementation",
        "player_environment_revision",
        "player_environment_digest_sha256",
        "information_policy_id",
    }
)


class AgenticSTSAuditError(ValueError):
    """Raised when the pinned source snapshot cannot be audited exactly."""


@dataclass(frozen=True)
class SourceFilePin:
    path: str
    bytes: int
    sha256: str

    def validate(self) -> None:
        if not self.path or Path(self.path).is_absolute() or ".." in Path(self.path).parts:
            raise AgenticSTSAuditError(f"invalid pinned source path: {self.path!r}")
        if (
            self.bytes <= 0
            or len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise AgenticSTSAuditError(f"invalid source file identity: {self.path}")


@dataclass(frozen=True)
class AgenticSTSSourcePin:
    dataset: str
    repo_id: str
    source_url: str
    revision: str
    license: str
    admitted_paths: tuple[str, ...]
    excluded_paths: tuple[str, ...]
    metadata_files: tuple[SourceFilePin, ...]
    representative_sample: SourceFilePin
    expected_manifest_runs: int
    expected_trajectory_files: int
    non_claims: tuple[str, ...]

    def validate(self) -> None:
        if self.dataset != "AgenticSTS-trajectories":
            raise AgenticSTSAuditError("unexpected AgenticSTS dataset identity")
        if self.repo_id != "AlayaLab/AgenticSTS-trajectories":
            raise AgenticSTSAuditError("unexpected AgenticSTS repository identity")
        if self.source_url != (
            "https://huggingface.co/datasets/AlayaLab/AgenticSTS-trajectories"
        ):
            raise AgenticSTSAuditError("unexpected AgenticSTS source URL")
        if len(self.revision) != 40 or any(c not in "0123456789abcdef" for c in self.revision):
            raise AgenticSTSAuditError("AgenticSTS revision must be an immutable Git SHA")
        if self.license != "CC-BY-4.0":
            raise AgenticSTSAuditError("only the declared CC-BY-4.0 subset is admitted")
        if self.admitted_paths != ("trajectories/*.jsonl.gz", "runs_history.jsonl"):
            raise AgenticSTSAuditError("AgenticSTS admitted path scope changed")
        if self.excluded_paths != ("competitors/*.tar.gz",):
            raise AgenticSTSAuditError("AgenticSTS excluded path scope changed")
        if self.expected_manifest_runs <= 0 or self.expected_trajectory_files <= 0:
            raise AgenticSTSAuditError("AgenticSTS expected inventory must be positive")
        for file in (*self.metadata_files, self.representative_sample):
            file.validate()


@dataclass
class TrajectoryAudit:
    event_records: int = 0
    decision_records: int = 0
    combat_decision_records: int = 0
    player_visible_state_records: int = 0
    explicit_chosen_action_records: int = 0
    catalog_like_records: int = 0
    complete_legal_action_catalog_records: int = 0
    uniquely_resolvable_chosen_action_records: int = 0
    stable_action_result_records: int = 0
    stable_successor_records: int = 0
    historical_game_version_records: int = 0
    game_seed_records: int = 0
    historical_policy_provenance_records: int = 0
    exact_environment_identity_records: int = 0
    sufficient_environment_policy_provenance_records: int = 0
    rank_eligible_accepted_records: int = 0
    decision_state_types: Counter[str] = field(default_factory=Counter)
    combat_action_types: Counter[str] = field(default_factory=Counter)
    rejection_reasons: Counter[str] = field(default_factory=Counter)

    def merge(self, other: TrajectoryAudit) -> None:
        scalar_fields = (
            "event_records",
            "decision_records",
            "combat_decision_records",
            "player_visible_state_records",
            "explicit_chosen_action_records",
            "catalog_like_records",
            "complete_legal_action_catalog_records",
            "uniquely_resolvable_chosen_action_records",
            "stable_action_result_records",
            "stable_successor_records",
            "historical_game_version_records",
            "game_seed_records",
            "historical_policy_provenance_records",
            "exact_environment_identity_records",
            "sufficient_environment_policy_provenance_records",
            "rank_eligible_accepted_records",
        )
        for name in scalar_fields:
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.decision_state_types.update(other.decision_state_types)
        self.combat_action_types.update(other.combat_action_types)
        self.rejection_reasons.update(other.rejection_reasons)

    def counts_dict(self) -> dict[str, int]:
        return {
            "total_event_records": self.event_records,
            "total_decision_records": self.decision_records,
            "combat_decision_records": self.combat_decision_records,
            "reconstructable_player_visible_state_records": self.player_visible_state_records,
            "explicit_chosen_action_records": self.explicit_chosen_action_records,
            "catalog_like_records": self.catalog_like_records,
            "complete_legal_action_catalog_records": self.complete_legal_action_catalog_records,
            "uniquely_resolvable_chosen_action_records": (
                self.uniquely_resolvable_chosen_action_records
            ),
            "stable_action_result_records": self.stable_action_result_records,
            "stable_successor_records": self.stable_successor_records,
            "historical_game_version_records": self.historical_game_version_records,
            "game_seed_records": self.game_seed_records,
            "historical_policy_provenance_records": (
                self.historical_policy_provenance_records
            ),
            "exact_environment_identity_records": self.exact_environment_identity_records,
            "sufficient_environment_policy_provenance_records": (
                self.sufficient_environment_policy_provenance_records
            ),
            "rank_eligible_accepted_records": self.rank_eligible_accepted_records,
        }


def load_agenticsts_source_pin(path: Path) -> AgenticSTSSourcePin:
    """Load and validate the checked-in immutable AgenticSTS source pin."""

    value = _json_object(path)
    if value.get("schema") != PIN_SCHEMA:
        raise AgenticSTSAuditError("unsupported AgenticSTS source pin schema")
    try:
        scope = _mapping(value["license_scope"], "license_scope")
        metadata = tuple(_file_pin(item) for item in _objects(value["metadata_files"]))
        pin = AgenticSTSSourcePin(
            dataset=str(value["dataset"]),
            repo_id=str(value["repo_id"]),
            source_url=str(value["source_url"]),
            revision=str(value["revision"]),
            license=str(value["license"]),
            admitted_paths=tuple(str(item) for item in _sequence(scope["admitted"])),
            excluded_paths=tuple(str(item) for item in _sequence(scope["excluded"])),
            metadata_files=metadata,
            representative_sample=_file_pin(_mapping(value["representative_sample"], "sample")),
            expected_manifest_runs=int(value["expected_manifest_runs"]),
            expected_trajectory_files=int(value["expected_trajectory_files"]),
            non_claims=tuple(str(item) for item in _sequence(value["non_claims"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AgenticSTSAuditError("invalid AgenticSTS source pin") from exc
    pin.validate()
    return pin


def audit_agenticsts_snapshot(snapshot: Path, pin: AgenticSTSSourcePin) -> dict[str, Any]:
    """Audit every official trajectory file without inferring missing evidence."""

    pin.validate()
    snapshot = snapshot.expanduser().resolve()
    if not snapshot.is_dir() or snapshot.name != pin.revision:
        raise AgenticSTSAuditError("snapshot path does not bind the pinned revision")
    verified_metadata = [_verify_pinned_file(snapshot, item) for item in pin.metadata_files]
    verified_sample = _verify_pinned_file(snapshot, pin.representative_sample)

    manifest = _json_object(snapshot / "manifest.json")
    manifest_rows = _objects(manifest.get("trajectories"))
    if len(manifest_rows) != pin.expected_manifest_runs:
        raise AgenticSTSAuditError("manifest run count does not match the pin")
    history = _read_history(snapshot / "runs_history.jsonl")
    trajectory_rows = [row for row in manifest_rows if row.get("has_trajectory") is True]
    if len(trajectory_rows) != pin.expected_trajectory_files:
        raise AgenticSTSAuditError("trajectory inventory does not match the pin")

    total = TrajectoryAudit()
    sample_counts: dict[str, int] | None = None
    file_identities: list[dict[str, Any]] = []
    game_versions: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    for entry in trajectory_rows:
        relative = str(entry.get("file", ""))
        if not relative.startswith("trajectories/") or not relative.endswith(".jsonl.gz"):
            raise AgenticSTSAuditError(f"manifest contains an inadmissible file: {relative!r}")
        path = snapshot / Path(relative)
        if not path.is_file():
            raise AgenticSTSAuditError(f"manifest trajectory is missing: {relative}")
        run_id = str(entry.get("run_id", ""))
        run_history = history.get(run_id)
        per_file = audit_agenticsts_trajectory(path, entry, run_history)
        total.merge(per_file)
        identity = {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        file_identities.append(identity)
        if relative == pin.representative_sample.path:
            sample_counts = per_file.counts_dict()
        game_versions[str(entry.get("game_version"))] += 1
        outcomes[str(entry.get("outcome"))] += 1
    if sample_counts is None:
        raise AgenticSTSAuditError("representative sample was not in the manifest")

    decision_denominator = total.decision_records
    combat_denominator = total.combat_decision_records
    accepted = total.rank_eligible_accepted_records
    return {
        "schema": AUDIT_SCHEMA,
        "status": (
            "agenticsts_insufficient_for_s1_smoke"
            if accepted < 1000
            else "agenticsts_candidate_for_s1_smoke"
        ),
        "source": {
            "dataset": pin.dataset,
            "repo_id": pin.repo_id,
            "source_url": pin.source_url,
            "revision": pin.revision,
            "license": pin.license,
            "admitted_paths": list(pin.admitted_paths),
            "excluded_paths": list(pin.excluded_paths),
            "verified_metadata": verified_metadata,
            "trajectory_files": len(file_identities),
            "trajectory_files_sha256": semantic_hash(file_identities),
        },
        "inventory": {
            "manifest_runs": len(manifest_rows),
            "trajectory_files": len(trajectory_rows),
            "history_rows": len(history),
            "outcomes": dict(sorted(outcomes.items())),
            "game_versions": dict(sorted(game_versions.items())),
        },
        "representative_sample": {
            **verified_sample,
            "counts": sample_counts,
        },
        "counts": total.counts_dict(),
        "decision_state_types": dict(sorted(total.decision_state_types.items())),
        "combat_action_types": dict(sorted(total.combat_action_types.items())),
        "strict_rejection_reasons": dict(sorted(total.rejection_reasons.items())),
        "acceptance": {
            "accepted_records": accepted,
            "of_all_decisions_percent": _percentage(accepted, decision_denominator),
            "of_combat_decisions_percent": _percentage(accepted, combat_denominator),
            "minimum_required_for_s1_smoke": 1000,
        },
        "missing_information": [
            "an explicit complete legal-action catalog for each decision",
            "a chosen action mapped uniquely to that complete catalog",
            "the game seed or an explicitly declared run/seed-root field",
            "exact game commit, assembly SHA-256 and MVID",
            "exact Host source/artifact SHA-256 and MVID",
            "exact Player Environment implementation revision and digest",
            "a source-bound stable successor object suitable for ResearchTransition",
        ],
        "required_current_teacher_collection": {
            "minimum_rank_eligible_decisions": 1000,
            "required": [
                "current admitted game/Host/Player Environment identity per episode",
                "whole episode/run/seed-root provenance",
                "stable player-visible pre-action state",
                "complete finite legal-action catalog from the authoritative environment",
                "exact executed action mapped one-to-one to that catalog",
                "stable post-action successor or explicit terminal/scope exit",
                "declared behavior-policy identity and source revision",
            ],
        },
        "non_claims": [
            *pin.non_claims,
            "Detailed historical combat states do not authorize reconstruction of legality.",
            "Sequential stable action results do not supply an exact current environment identity.",
            "The audit does not create Parquet, a split manifest, or a training configuration.",
        ],
    }


def audit_agenticsts_trajectory(
    path: Path,
    manifest_entry: Mapping[str, Any],
    run_history: Mapping[str, Any] | None,
) -> TrajectoryAudit:
    """Audit one gzip event log; exposed separately for deterministic unit tests."""

    events: list[tuple[int, Mapping[str, Any]]] = []
    audit = TrajectoryAudit()
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise AgenticSTSAuditError(
                        f"malformed trajectory JSON: {path}:{index + 1}"
                    ) from exc
                if not isinstance(value, Mapping):
                    raise AgenticSTSAuditError(
                        f"trajectory row is not an object: {path}:{index + 1}"
                    )
                row = cast(Mapping[str, Any], value)
                audit.event_records += 1
                if row.get("event") in {"state", "decision", "action_result"}:
                    events.append((index, row))
    except OSError as exc:
        raise AgenticSTSAuditError(f"cannot read trajectory: {path}") from exc

    states_by_step: defaultdict[int, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    results_by_step: defaultdict[int, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    ordered_states: list[tuple[int, int, Mapping[str, Any]]] = []
    decisions: list[tuple[int, Mapping[str, Any]]] = []
    for index, row in events:
        step = row.get("step")
        if isinstance(step, int) and not isinstance(step, bool):
            if row.get("event") == "state":
                states_by_step[step].append((index, row))
                ordered_states.append((index, step, row))
            elif row.get("event") == "action_result":
                results_by_step[step].append((index, row))
            elif row.get("event") == "decision":
                decisions.append((index, row))

    for index, decision in decisions:
        audit.decision_records += 1
        state_type = str(decision.get("state_type"))
        audit.decision_state_types[state_type] += 1
        if state_type not in COMBAT_STATE_TYPES:
            continue
        audit.combat_decision_records += 1
        chosen = decision.get("action")
        action_type = (
            str(chosen.get("action")) if isinstance(chosen, Mapping) else "missing"
        )
        audit.combat_action_types[action_type] += 1
        explicit_chosen = isinstance(chosen, Mapping) and bool(str(chosen.get("action", "")))
        if explicit_chosen:
            audit.explicit_chosen_action_records += 1

        step = cast(int, decision["step"])
        state = _latest_before(states_by_step.get(step, []), index)
        has_state = state is not None and _has_reconstructable_combat_state(state)
        if has_state:
            audit.player_visible_state_records += 1

        catalog, complete = _explicit_catalog(decision, state)
        if catalog is not None:
            audit.catalog_like_records += 1
        if complete:
            audit.complete_legal_action_catalog_records += 1
        chosen_unique = complete and _chosen_matches_once(chosen, catalog)
        if chosen_unique:
            audit.uniquely_resolvable_chosen_action_records += 1

        result_index, result = _matching_action_result(
            results_by_step.get(step, []), index, chosen
        )
        stable_result = result is not None and result.get("mcp_stable") is True
        if stable_result:
            audit.stable_action_result_records += 1
        successor = _next_state(ordered_states, result_index if result_index is not None else index)
        stable_successor = stable_result and successor is not None
        if stable_successor:
            audit.stable_successor_records += 1

        game_version_known = bool(str(manifest_entry.get("game_version") or "").strip())
        if game_version_known:
            audit.historical_game_version_records += 1
        seed_known = _has_explicit_seed(decision, state, manifest_entry, run_history)
        if seed_known:
            audit.game_seed_records += 1
        policy_known = _has_historical_policy(decision, run_history)
        if policy_known:
            audit.historical_policy_provenance_records += 1
        environment_known = _has_exact_environment(decision, state, manifest_entry, run_history)
        if environment_known:
            audit.exact_environment_identity_records += 1
        provenance_sufficient = environment_known and policy_known and seed_known
        if provenance_sufficient:
            audit.sufficient_environment_policy_provenance_records += 1

        requirements = {
            "missing_reconstructable_player_visible_state": has_state,
            "missing_complete_legal_action_catalog": complete,
            "missing_uniquely_resolvable_chosen_action": chosen_unique,
            "missing_stable_successor": stable_successor,
            "missing_game_seed_or_declared_root": seed_known,
            "missing_historical_policy_provenance": policy_known,
            "missing_exact_environment_identity": environment_known,
        }
        for reason, present in requirements.items():
            if not present:
                audit.rejection_reasons[reason] += 1
        if all(requirements.values()):
            audit.rank_eligible_accepted_records += 1
    return audit


def _latest_before(
    rows: Sequence[tuple[int, Mapping[str, Any]]], index: int
) -> Mapping[str, Any] | None:
    matches = [row for row_index, row in rows if row_index < index]
    return matches[-1] if matches else None


def _next_state(
    states: Sequence[tuple[int, int, Mapping[str, Any]]], index: int
) -> Mapping[str, Any] | None:
    return next((row for row_index, _step, row in states if row_index > index), None)


def _has_reconstructable_combat_state(state: Mapping[str, Any]) -> bool:
    combat = state.get("combat")
    if not isinstance(combat, Mapping):
        return False
    player = combat.get("player")
    return (
        isinstance(player, Mapping)
        and isinstance(player.get("hand"), list)
        and isinstance(combat.get("enemies"), list)
        and isinstance(state.get("deck"), list)
        and isinstance(combat.get("round"), int)
        and isinstance(combat.get("is_play_phase"), bool)
    )


def _explicit_catalog(
    decision: Mapping[str, Any], state: Mapping[str, Any] | None
) -> tuple[Sequence[Any] | None, bool]:
    for owner in (decision, state):
        if owner is None:
            continue
        found = _find_catalog(owner)
        if found is not None:
            catalog, container = found
            completeness = owner.get("legal_action_completeness")
            eligibility = owner.get("eligibility")
            if isinstance(eligibility, Mapping):
                completeness = eligibility.get("legal_action_completeness", completeness)
            status = container.get("status") if isinstance(container, Mapping) else None
            return catalog, completeness == "complete" or status == "complete"
    return None, False


def _find_catalog(value: Any) -> tuple[Sequence[Any], Any] | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in CATALOG_KEYS:
                if isinstance(item, Sequence) and not isinstance(
                    item, (str, bytes, bytearray)
                ):
                    return item, value
                if isinstance(item, Mapping):
                    actions = item.get("actions")
                    if isinstance(actions, Sequence) and not isinstance(
                        actions, (str, bytes, bytearray)
                    ):
                        return actions, item
            nested = _find_catalog(item)
            if nested is not None:
                return nested
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            nested = _find_catalog(item)
            if nested is not None:
                return nested
    return None


def _chosen_matches_once(chosen: Any, catalog: Sequence[Any] | None) -> bool:
    if not isinstance(chosen, Mapping) or catalog is None:
        return False
    fingerprint = _action_fingerprint(chosen)
    matches = [item for item in catalog if _action_fingerprint(item) == fingerprint]
    return len(matches) == 1


def _action_fingerprint(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    action = value.get("action", value.get("kind"))
    params = value.get("params")
    if params is None:
        params = {key: item for key, item in value.items() if key not in {"action", "kind"}}
    return semantic_hash({"action": action, "params": params})


def _matching_action_result(
    results: Sequence[tuple[int, Mapping[str, Any]]],
    decision_index: int,
    chosen: Any,
) -> tuple[int | None, Mapping[str, Any] | None]:
    action_type = chosen.get("action") if isinstance(chosen, Mapping) else None
    candidates = [
        (index, row)
        for index, row in results
        if row.get("action") == action_type and index < decision_index
    ]
    if not candidates:
        candidates = [(index, row) for index, row in results if row.get("action") == action_type]
    return candidates[-1] if candidates else (None, None)


def _has_explicit_seed(*values: Mapping[str, Any] | None) -> bool:
    return any(value is not None and bool(str(value.get("seed") or "").strip()) for value in values)


def _has_historical_policy(
    decision: Mapping[str, Any], run_history: Mapping[str, Any] | None
) -> bool:
    if run_history is None:
        return False
    return (
        bool(str(decision.get("source") or "").strip())
        and bool(str(run_history.get("profile_hash") or "").strip())
        and isinstance(run_history.get("model_profile"), Mapping)
    )


def _has_exact_environment(*values: Mapping[str, Any] | None) -> bool:
    for value in values:
        if value is None:
            continue
        environment = value.get("environment")
        if (
            isinstance(environment, Mapping)
            and ENVIRONMENT_FIELDS.issubset(environment)
            and all(
                bool(str(environment.get(field) or "").strip())
                for field in ENVIRONMENT_FIELDS
            )
        ):
            return True
    return False


def _read_history(path: Path) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    with path.open("rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AgenticSTSAuditError(
                    f"malformed runs_history.jsonl line {line_number}"
                ) from exc
            if not isinstance(value, Mapping) or not str(value.get("run_id", "")):
                raise AgenticSTSAuditError(f"invalid runs_history.jsonl line {line_number}")
            run_id = str(value["run_id"])
            if run_id in result:
                raise AgenticSTSAuditError(f"duplicate run history identity: {run_id}")
            result[run_id] = cast(Mapping[str, Any], value)
    return result


def _verify_pinned_file(snapshot: Path, pin: SourceFilePin) -> dict[str, Any]:
    path = snapshot / Path(pin.path)
    if not path.is_file():
        raise AgenticSTSAuditError(f"pinned source file is missing: {pin.path}")
    size = path.stat().st_size
    digest = _sha256(path)
    if size != pin.bytes or digest != pin.sha256:
        raise AgenticSTSAuditError(
            f"pinned source file identity mismatch: {pin.path}: "
            f"expected {pin.bytes}/{pin.sha256}, got {size}/{digest}"
        )
    return {"path": pin.path, "bytes": size, "sha256": digest}


def _file_pin(value: Mapping[str, Any]) -> SourceFilePin:
    return SourceFilePin(str(value["path"]), int(value["bytes"]), str(value["sha256"]))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percentage(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator * 100.0 / denominator


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgenticSTSAuditError(f"cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise AgenticSTSAuditError(f"JSON document must be an object: {path}")
    return cast(dict[str, Any], value)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AgenticSTSAuditError(f"{name} must be an object")
    return cast(Mapping[str, Any], value)


def _sequence(value: Any) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise AgenticSTSAuditError("value must be an array")
    return value


def _objects(value: Any) -> Sequence[Mapping[str, Any]]:
    sequence = _sequence(value)
    if any(not isinstance(item, Mapping) for item in sequence):
        raise AgenticSTSAuditError("array must contain objects")
    return cast(Sequence[Mapping[str, Any]], sequence)
