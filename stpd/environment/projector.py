"""Project complete fair-player snapshots into consumer-neutral research semantics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..canonical import semantic_hash, to_json_value
from ..contracts import ContractError
from ..representation import (
    DecisionFamily,
    ExecutionEnvelope,
    ResearchAction,
    ResearchState,
    ensure_action_catalog_alignment,
)

_RUNTIME_KEYS = {
    "bound_action_id",
    "snapshot_id",
    "mutation_request_id",
    "request_id",
    "runtime_instance_id",
    "environment_fingerprint",
    "controller_lease_id",
    "entity_id",
    "referent_id",
    "interaction_id",
    "read_id",
    "observed_at",
    "sequence",
}

_ROLE_PREFIX = {
    "hand_card": "H",
    "card": "C",
    "enemy": "E",
    "monster": "E",
    "potion": "P",
    "selection": "S",
    "option": "O",
    "choice": "O",
    "control": "U",
}


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if str(key).lower() not in _RUNTIME_KEYS and not str(key).lower().startswith("native_")
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize(item) for item in value]
    return to_json_value(value)


def _decision_family(interaction_kind: str) -> DecisionFamily:
    normalized = interaction_kind.lower()
    if "choice" in normalized or "generated" in normalized:
        return DecisionFamily.CARD_CHOICE
    if "selection" in normalized or "selector" in normalized:
        return DecisionFamily.CARD_SELECTION
    if normalized == "combat_turn":
        return DecisionFamily.TURN_ACTION
    raise ContractError(f"interaction is outside STPD v0 combat scope: {interaction_kind}")


def _action_kind(verb: str, family: DecisionFamily, subject_role: str | None) -> str:
    if family is DecisionFamily.TURN_ACTION and verb == "play":
        return "play_card"
    if family is DecisionFamily.TURN_ACTION and verb == "use":
        return "use_potion"
    if family is DecisionFamily.TURN_ACTION and verb == "end_turn":
        return "end_turn"
    if family is DecisionFamily.CARD_SELECTION and verb in {"select", "deselect"}:
        return f"{verb}_card"
    if family is DecisionFamily.CARD_SELECTION and verb in {"confirm", "cancel"}:
        return f"{verb}_selection"
    if family is DecisionFamily.CARD_CHOICE and verb == "skip":
        return "skip_choice"
    if family is DecisionFamily.CARD_CHOICE and verb == "activate":
        return "choose_card"
    raise ContractError(
        f"unsupported v0 action verb/family: {verb}/{family.value}/{subject_role or 'control'}"
    )


@dataclass(frozen=True)
class ProjectedDecision:
    state: ResearchState
    actions: tuple[ResearchAction, ...]
    envelopes: tuple[ExecutionEnvelope, ...]


class ResearchProjectorV0:
    """The only v0 mapping from Player Environment truth to research objects."""

    def project(
        self,
        snapshot: Mapping[str, Any],
        reads: Mapping[str, Mapping[str, Any]],
        *,
        game_version: str,
        game_commit: str,
        mutation_request_prefix: str,
    ) -> ProjectedDecision:
        if snapshot.get("status") != "interactive":
            raise ContractError("research projection requires a stable interactive snapshot")
        completeness = snapshot.get("completeness")
        if not isinstance(completeness, Mapping) or completeness.get("status") != "complete":
            raise ContractError("snapshot visible-information completeness is not complete")
        catalog = snapshot.get("bound_actions")
        if not isinstance(catalog, Mapping) or catalog.get("status") != "complete":
            raise ContractError("snapshot finite BoundAction catalog is not complete")
        actions_raw = catalog.get("actions")
        if not isinstance(actions_raw, Sequence) or not actions_raw:
            raise ContractError("snapshot requires a non-empty action catalog")
        snapshot_id = snapshot.get("snapshot_id")
        if not isinstance(snapshot_id, str) or not snapshot_id:
            raise ContractError("snapshot identity is missing")
        interaction = snapshot.get("interaction")
        if not isinstance(interaction, Mapping):
            raise ContractError("snapshot interaction is missing")
        interaction_content = interaction.get("content")
        context = (
            interaction_content.get("context")
            if isinstance(interaction_content, Mapping)
            else None
        )
        if not isinstance(context, Mapping) or context.get("kind") != "combat":
            raise ContractError("STPD v0 projection requires explicit Combat semantic context")
        interaction_kind = str(interaction.get("kind", ""))
        family = _decision_family(interaction_kind)
        referents_raw = snapshot.get("referents")
        if not isinstance(referents_raw, Sequence):
            raise ContractError("snapshot referents must be a sequence")
        local_by_id: dict[str, str] = {}
        semantic_by_id: dict[str, dict[str, Any]] = {}
        counters: Counter[str] = Counter()
        semantic_referents: list[dict[str, Any]] = []
        for referent in referents_raw:
            if not isinstance(referent, Mapping):
                raise ContractError("referent must be an object")
            identifier = referent.get("referent_id")
            if not isinstance(identifier, str) or not identifier:
                raise ContractError("referent identity is missing")
            role = str(referent.get("role", "referent"))
            prefix = _ROLE_PREFIX.get(role, _ROLE_PREFIX.get(str(referent.get("kind")), "R"))
            local_ref = f"{prefix}{counters[prefix]}"
            counters[prefix] += 1
            semantic = _sanitize(referent)
            if not isinstance(semantic, dict):
                raise ContractError("sanitized referent must remain an object")
            semantic["local_ref"] = local_ref
            local_by_id[identifier] = local_ref
            semantic_by_id[identifier] = semantic
            semantic_referents.append(semantic)
        state = ResearchState(
            information_policy_id=str(
                snapshot.get("information_policy", {}).get("id", "")
                if isinstance(snapshot.get("information_policy"), Mapping)
                else ""
            ),
            game_version=game_version,
            game_commit=game_commit,
            decision_mode="combat",
            decision_family=family,
            surface=interaction_kind,
            facts={
                "run": _sanitize(snapshot.get("persistent")),
                "interaction": _sanitize(interaction),
                "referents": semantic_referents,
            },
            reads={kind: _sanitize(value.get("content", value)) for kind, value in reads.items()},
        )
        semantic_actions: list[ResearchAction] = []
        envelopes: list[ExecutionEnvelope] = []
        action_keys: set[str] = set()
        for action_raw in actions_raw:
            if not isinstance(action_raw, Mapping):
                raise ContractError("BoundAction must be an object")
            bound_id = action_raw.get("bound_action_id")
            verb = action_raw.get("verb")
            if not isinstance(bound_id, str) or not bound_id or not isinstance(verb, str):
                raise ContractError("BoundAction identity or verb is missing")
            subject_id = action_raw.get("subject_referent_id")
            subject = semantic_by_id.get(str(subject_id)) if subject_id is not None else None
            if subject_id is not None and subject is None:
                raise ContractError("BoundAction subject is not a current visible referent")
            arguments: list[dict[str, Any]] = []
            for argument in action_raw.get("arguments", []):
                if not isinstance(argument, Mapping):
                    raise ContractError("BoundAction argument must be an object")
                referent_id = str(argument.get("referent_id", ""))
                if referent_id not in semantic_by_id:
                    raise ContractError("BoundAction argument is not a current visible referent")
                arguments.append(
                    {
                        "role": str(argument.get("role", "argument")),
                        "referent": semantic_by_id[referent_id],
                    }
                )
            subject_properties = subject.get("properties", {}) if subject else {}
            if not isinstance(subject_properties, Mapping):
                subject_properties = {}
            action_payload = {
                "kind": _action_kind(
                    verb, family, None if subject is None else str(subject.get("role", ""))
                ),
                "subject": subject,
                "arguments": arguments,
                "visible_cost": subject_properties.get(
                    "current_cost", subject_properties.get("cost")
                ),
                "visible_effect": subject_properties.get("description"),
            }
            action_key = f"a:{semantic_hash(action_payload)[:24]}"
            if action_key in action_keys:
                raise ContractError(
                    "two current BoundActions have indistinguishable semantic identity"
                )
            action_keys.add(action_key)
            action = ResearchAction(action_key=action_key, **action_payload)
            semantic_actions.append(action)
            envelopes.append(
                ExecutionEnvelope(
                    action_key,
                    snapshot_id,
                    bound_id,
                    f"{mutation_request_prefix}-{action_key[2:]}",
                )
            )
        ensure_action_catalog_alignment(semantic_actions, envelopes)
        state.validate()
        return ProjectedDecision(state, tuple(semantic_actions), tuple(envelopes))
