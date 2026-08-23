"""Frozen STPD v0 research objects and deterministic model serialization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast

from .canonical import canonical_json, reject_model_input_leakage, semantic_hash, to_json_value
from .contracts import ContractError, EnvironmentIdentity, TransitionEligibility


class DecisionFamily(StrEnum):
    TURN_ACTION = "turn_action"
    CARD_SELECTION = "card_selection"
    CARD_CHOICE = "card_choice"


class InputProfile(StrEnum):
    LITE = "stpd-combat-v0-lite"
    STANDARD = "stpd-combat-v0-standard"
    FULL = "stpd-combat-v0-full"


@dataclass(frozen=True)
class PolicyProvenance:
    source: str
    version: str
    config_hash: str
    teacher_confidence: float | None = None

    def validate(self) -> None:
        for name, value in (
            ("source", self.source),
            ("version", self.version),
            ("config_hash", self.config_hash),
        ):
            if not value.strip():
                raise ContractError(f"policy.{name} must be non-empty")
        if self.teacher_confidence is not None and not 0 <= self.teacher_confidence <= 1:
            raise ContractError("teacher_confidence must be in [0, 1]")


@dataclass(frozen=True)
class ResearchState:
    """Model-independent fair-player truth for one coherent stable decision."""

    information_policy_id: str
    game_version: str
    game_commit: str
    decision_mode: str
    decision_family: DecisionFamily
    surface: str
    facts: Mapping[str, Any]
    reads: Mapping[str, Any] = field(default_factory=dict)
    schema: str = field(default="stpd/research-state-v0", init=False)

    def semantic_payload(self) -> dict[str, Any]:
        payload = {
            "schema": self.schema,
            "information_policy_id": self.information_policy_id,
            "game_version": self.game_version,
            "game_commit": self.game_commit,
            "decision_mode": self.decision_mode,
            "decision_family": self.decision_family.value,
            "surface": self.surface,
            "facts": self.facts,
            "reads": self.reads,
        }
        reject_model_input_leakage(payload)
        return cast(dict[str, Any], to_json_value(payload))

    @property
    def state_hash(self) -> str:
        return semantic_hash(self.semantic_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_payload()
        payload["state_hash"] = self.state_hash
        return payload

    def validate(self) -> None:
        for name, value in (
            ("information_policy_id", self.information_policy_id),
            ("game_version", self.game_version),
            ("game_commit", self.game_commit),
            ("decision_mode", self.decision_mode),
            ("surface", self.surface),
        ):
            if not value.strip():
                raise ContractError(f"state.{name} must be non-empty")
        self.semantic_payload()


@dataclass(frozen=True)
class ResearchAction:
    """Visible semantic meaning of one current legal BoundAction candidate."""

    action_key: str
    kind: str
    subject: Mapping[str, Any] | None = None
    arguments: tuple[Mapping[str, Any], ...] = ()
    visible_cost: str | int | float | None = None
    visible_effect: str | None = None
    schema: str = field(default="stpd/research-action-v0", init=False)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": self.schema,
            "action_key": self.action_key,
            "kind": self.kind,
            "subject": self.subject,
            "arguments": self.arguments,
            "visible_cost": self.visible_cost,
            "visible_effect": self.visible_effect,
        }
        reject_model_input_leakage(payload)
        return cast(dict[str, Any], to_json_value(payload))

    def validate(self) -> None:
        if not self.action_key.strip() or not self.kind.strip():
            raise ContractError("action_key and kind must be non-empty")
        self.to_dict()


@dataclass(frozen=True)
class ExecutionEnvelope:
    """Ephemeral authority linkage; never serialized into model input."""

    action_key: str
    snapshot_id: str
    bound_action_id: str
    mutation_request_id: str

    def validate(self) -> None:
        for name, value in (
            ("action_key", self.action_key),
            ("snapshot_id", self.snapshot_id),
            ("bound_action_id", self.bound_action_id),
            ("mutation_request_id", self.mutation_request_id),
        ):
            if not value.strip():
                raise ContractError(f"execution.{name} must be non-empty")


@dataclass(frozen=True)
class ResearchTransition:
    """One stable decision, executed action, and stable successor/scope exit."""

    transition_id: str
    episode_id: str
    step_index: int
    seed: str
    environment: EnvironmentIdentity
    policy: PolicyProvenance
    decision_mode: str
    surface: str
    input_profile: InputProfile
    eligibility: TransitionEligibility
    state: ResearchState
    legal_actions: tuple[ResearchAction, ...]
    chosen_action: ResearchAction
    successor: ResearchState | None
    terminal: bool
    scope_exit: bool
    outcome: Mapping[str, Any] | None
    raw_ref: str
    schema: str = field(default="stpd/research-transition-v0", init=False)

    def validate(self) -> None:
        for name, value in (
            ("transition_id", self.transition_id),
            ("episode_id", self.episode_id),
            ("seed", self.seed),
            ("decision_mode", self.decision_mode),
            ("surface", self.surface),
            ("raw_ref", self.raw_ref),
        ):
            if not value.strip():
                raise ContractError(f"transition.{name} must be non-empty")
        if self.step_index < 0:
            raise ContractError("step_index must be non-negative")
        self.environment.validate()
        self.policy.validate()
        self.eligibility.validate()
        self.state.validate()
        if not self.legal_actions:
            raise ContractError("a transition requires a non-empty legal action catalog")
        for action in self.legal_actions:
            action.validate()
        action_keys = [action.action_key for action in self.legal_actions]
        if len(action_keys) != len(set(action_keys)):
            raise ContractError("legal action_key values must be unique")
        if self.chosen_action.action_key not in action_keys:
            raise ContractError("chosen_action must be present in legal_actions")
        if self.successor is None and not (self.terminal or self.scope_exit):
            raise ContractError("a non-terminal in-scope transition requires a stable successor")
        if self.successor is not None:
            self.successor.validate()
        if (
            self.eligibility.transition
            and self.successor is None
            and not (self.terminal or self.scope_exit)
        ):
            raise ContractError("transition eligibility requires stable successor semantics")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return cast(
            dict[str, Any],
            to_json_value(
                {
                    "schema": self.schema,
                    "transition_id": self.transition_id,
                    "episode_id": self.episode_id,
                    "step_index": self.step_index,
                    "seed": self.seed,
                    "environment": self.environment,
                    "policy": self.policy,
                    "decision_mode": self.decision_mode,
                    "surface": self.surface,
                    "input_profile": self.input_profile.value,
                    "eligibility": self.eligibility.to_dict(),
                    "state": self.state.to_dict(),
                    "legal_actions": [action.to_dict() for action in self.legal_actions],
                    "chosen_action": self.chosen_action.to_dict(),
                    "successor": None if self.successor is None else self.successor.to_dict(),
                    "terminal": self.terminal,
                    "scope_exit": self.scope_exit,
                    "outcome": self.outcome,
                    "raw_ref": self.raw_ref,
                }
            ),
        )


_SECTION_ORDER = (
    "header",
    "run",
    "run_modifiers",
    "relic_details",
    "relics",
    "potions",
    "card_details",
    "deck",
    "combat",
    "player_status",
    "companions",
    "orbs",
    "enemies",
    "hand",
    "piles",
    "interaction",
    "selection_cards",
    "choice_cards",
    "footer",
)


class ModelSerializerV0:
    """Deterministic strategy-free ModelState/ModelAction serializer."""

    version = "stpd-model-serialization-v0"

    def __init__(self, profile: InputProfile = InputProfile.STANDARD) -> None:
        self.profile = profile
        self.profile_id = profile.value

    def _profile_facts(self, state: ResearchState) -> dict[str, Any]:
        facts = to_json_value(state.facts)
        reads = to_json_value(state.reads)
        if self.profile is InputProfile.LITE:
            facts.pop("card_details", None)
            facts.pop("relic_details", None)
            reads = _counts_only(reads)
        elif self.profile is InputProfile.STANDARD:
            reads = _counts_only(reads)
        return {"facts": facts, "reads": reads}

    def serialize_state(self, research_state: Mapping[str, Any] | ResearchState) -> str:
        state = _coerce_state(research_state)
        state.validate()
        profiled = self._profile_facts(state)
        facts = profiled["facts"]
        lines = [
            f"[STPD_STATE version={self.version} profile={self.profile_id}]",
            f"decision_mode={canonical_json(state.decision_mode)}",
            f"decision_family={canonical_json(state.decision_family.value)}",
            f"surface={canonical_json(state.surface)}",
            f"information_policy={canonical_json(state.information_policy_id)}",
        ]
        emitted: set[str] = set()
        for section in _SECTION_ORDER:
            if section in facts:
                lines.append(f"{section.upper()}={canonical_json(facts[section])}")
                emitted.add(section)
        for key in sorted(set(facts) - emitted):
            lines.append(f"{key.upper()}={canonical_json(facts[key])}")
        if profiled["reads"]:
            lines.append(f"READS={canonical_json(profiled['reads'])}")
        lines.append("[/STPD_STATE]")
        result = "\n".join(lines)
        reject_model_input_leakage({"serialized": result})
        return result

    def serialize_action(self, research_action: Mapping[str, Any] | ResearchAction) -> str:
        action = _coerce_action(research_action)
        action.validate()
        payload = action.to_dict()
        lines = [f"[STPD_ACTION version={self.version}]", f"kind={canonical_json(action.kind)}"]
        for key in ("subject", "arguments", "visible_cost", "visible_effect"):
            if payload[key] not in (None, [], ()):
                lines.append(f"{key}={canonical_json(payload[key])}")
        lines.append("[/STPD_ACTION]")
        result = "\n".join(lines)
        reject_model_input_leakage({"serialized": result})
        return result


class ModelSerializerV1(ModelSerializerV0):
    """Standard serializer without duplicated turn-action referent payloads."""

    version = "stpd-model-serialization-v1"

    def _profile_facts(self, state: ResearchState) -> dict[str, Any]:
        profiled = super()._profile_facts(state)
        facts = profiled["facts"]
        interaction = facts.get("interaction")
        content = interaction.get("content") if isinstance(interaction, Mapping) else None
        context = content.get("context") if isinstance(content, Mapping) else None
        if (
            self.profile is InputProfile.STANDARD
            and state.decision_family is DecisionFamily.TURN_ACTION
            and isinstance(context, Mapping)
            and context.get("kind") == "combat"
        ):
            facts.pop("referents", None)
        return profiled


def model_serializer(
    version: str, profile: InputProfile = InputProfile.STANDARD
) -> ModelSerializerV0:
    serializers = {
        ModelSerializerV0.version: ModelSerializerV0,
        ModelSerializerV1.version: ModelSerializerV1,
    }
    serializer_type = serializers.get(version)
    if serializer_type is None:
        raise ContractError(f"unsupported model serializer version: {version}")
    return serializer_type(profile)


def _counts_only(value: Any) -> Any:
    """Retain visible collection sizes while omitting verbose inspectable contents."""

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"cards", "items", "entries", "contents"} and isinstance(item, list):
                result[f"{key}_count"] = len(item)
            else:
                result[key] = _counts_only(item)
        return result
    if isinstance(value, list):
        return [_counts_only(item) for item in value]
    return value


def _coerce_state(value: Mapping[str, Any] | ResearchState) -> ResearchState:
    if isinstance(value, ResearchState):
        return value
    if value.get("schema") != "stpd/research-state-v0":
        raise ContractError("ModelSerializerV0 received an unsupported ResearchState schema")
    facts = value.get("facts")
    reads = value.get("reads", {})
    if not isinstance(facts, Mapping) or not isinstance(reads, Mapping):
        raise ContractError("serialized ResearchState facts/reads must be objects")
    try:
        state = ResearchState(
            information_policy_id=str(value["information_policy_id"]),
            game_version=str(value["game_version"]),
            game_commit=str(value["game_commit"]),
            decision_mode=str(value["decision_mode"]),
            decision_family=DecisionFamily(str(value["decision_family"])),
            surface=str(value["surface"]),
            facts=facts,
            reads=reads,
        )
    except (KeyError, ValueError) as error:
        raise ContractError("serialized ResearchState is incomplete") from error
    expected_hash = value.get("state_hash")
    if expected_hash is not None and expected_hash != state.state_hash:
        raise ContractError("serialized ResearchState hash mismatch")
    return state


def _coerce_action(value: Mapping[str, Any] | ResearchAction) -> ResearchAction:
    if isinstance(value, ResearchAction):
        return value
    if value.get("schema") != "stpd/research-action-v0":
        raise ContractError("ModelSerializerV0 received an unsupported ResearchAction schema")
    arguments = value.get("arguments", ())
    subject = value.get("subject")
    if not isinstance(arguments, Sequence) or isinstance(arguments, (str, bytes)):
        raise ContractError("serialized ResearchAction arguments must be an array")
    if subject is not None and not isinstance(subject, Mapping):
        raise ContractError("serialized ResearchAction subject must be an object or null")
    if not all(isinstance(argument, Mapping) for argument in arguments):
        raise ContractError("serialized ResearchAction argument must be an object")
    try:
        return ResearchAction(
            action_key=str(value["action_key"]),
            kind=str(value["kind"]),
            subject=cast(Mapping[str, Any] | None, subject),
            arguments=tuple(cast(Sequence[Mapping[str, Any]], arguments)),
            visible_cost=cast(str | int | float | None, value.get("visible_cost")),
            visible_effect=cast(str | None, value.get("visible_effect")),
        )
    except KeyError as error:
        raise ContractError("serialized ResearchAction is incomplete") from error


def ensure_action_catalog_alignment(
    actions: Sequence[ResearchAction], envelopes: Sequence[ExecutionEnvelope]
) -> None:
    """Ensure semantic candidates map one-to-one onto current execution authority."""

    action_keys = [action.action_key for action in actions]
    envelope_keys = [envelope.action_key for envelope in envelopes]
    if len(action_keys) != len(set(action_keys)):
        raise ContractError("research action keys must be unique")
    if len(envelope_keys) != len(set(envelope_keys)):
        raise ContractError("execution envelope action keys must be unique")
    if set(action_keys) != set(envelope_keys):
        raise ContractError("semantic action catalog and execution envelopes are not bijective")
