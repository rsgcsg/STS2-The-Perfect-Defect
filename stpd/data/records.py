"""Strict reconstruction helpers for canonical ResearchTransition JSON records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..contracts import ContractError
from ..representation import DecisionFamily, ResearchAction, ResearchState


def research_state_from_record(value: Mapping[str, Any]) -> ResearchState:
    """Reconstruct and validate one frozen research state without filling missing fields."""

    try:
        state = ResearchState(
            information_policy_id=str(value["information_policy_id"]),
            game_version=str(value["game_version"]),
            game_commit=str(value["game_commit"]),
            decision_mode=str(value["decision_mode"]),
            decision_family=DecisionFamily(str(value["decision_family"])),
            surface=str(value["surface"]),
            facts=_mapping(value["facts"], "state.facts"),
            reads=_mapping(value["reads"], "state.reads"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("invalid canonical research state record") from exc
    state.validate()
    if value.get("schema") != state.schema or value.get("state_hash") != state.state_hash:
        raise ContractError("canonical research state schema or hash mismatch")
    return state


def research_action_from_record(value: Mapping[str, Any]) -> ResearchAction:
    """Reconstruct and validate one frozen research action without execution authority."""

    try:
        subject_value = value["subject"]
        action = ResearchAction(
            action_key=str(value["action_key"]),
            kind=str(value["kind"]),
            subject=(None if subject_value is None else _mapping(subject_value, "action.subject")),
            arguments=tuple(
                _mapping(item, "action.argument")
                for item in _sequence(value["arguments"], "action.arguments")
            ),
            visible_cost=value["visible_cost"],
            visible_effect=(
                None if value["visible_effect"] is None else str(value["visible_effect"])
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("invalid canonical research action record") from exc
    action.validate()
    if value.get("schema") != action.schema or action.to_dict() != dict(value):
        raise ContractError("canonical research action payload mismatch")
    return action


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be an object")
    return value


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ContractError(f"{name} must be an array")
    return value
