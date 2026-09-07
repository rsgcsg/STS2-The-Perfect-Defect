"""Provisional shared Full-Run model views; no scene-specific scoring branches."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..canonical import canonical_json, semantic_hash
from ..json_boundary import BoundaryError
from .contracts import ResearchTransitionV1, SemanticAction, SemanticState

SERIALIZER_VERSION = "stpd-fullrun-provisional-v1"
PROFILE_LEVEL = {"lite": 0, "standard": 1, "full": 2}
_FORBIDDEN = frozenset(
    {
        "boundactionid",
        "snapshotid",
        "mutationrequestid",
        "requestid",
        "runtimeinstanceid",
        "processid",
        "controllerleaseid",
        "nativeobjectid",
        "nativeoperand",
        "teacheridentity",
        "modelidentity",
        "futureoutcome",
        "draworder",
        "hiddenrng",
        "timestamp",
        "createdat",
        "capturedat",
        "runid",
        "episodeid",
        "transitionid",
        "chosenkey",
        "chosenaction",
        "candidateindex",
        "candidateposition",
        "candidateorder",
        "selectedindex",
        "successor",
        "runoutcome",
        "teachermetadata",
        "provenance",
        "commitref",
        "evidenceref",
    }
)


def reject_leakage(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized in _FORBIDDEN or normalized.startswith("native"):
                raise BoundaryError("model_view", "forbidden_runtime_or_future_feature")
            reject_leakage(item)
    elif isinstance(value, list):
        for item in value:
            reject_leakage(item)


@dataclass(frozen=True)
class FullRunSerializer:
    profile: str = "standard"

    def __post_init__(self) -> None:
        if self.profile not in PROFILE_LEVEL:
            raise BoundaryError("serializer", "unknown_profile")

    @property
    def identity(self) -> dict[str, str]:
        return {"version": SERIALIZER_VERSION, "profile": self.profile, "status": "provisional"}

    def state_content(self, state: SemanticState) -> dict[str, Any]:
        run = state.run.value()
        if self.profile == "lite":
            run = {
                key: value
                for key, value in run.items()
                if key
                in {
                    "character",
                    "act",
                    "floor",
                    "hp",
                    "max_hp",
                    "gold",
                    "run_modifiers",
                }
            }
        result = {
            "RUN": run,
            "DECISION": state.decision.value(),
            "VISIBLE_ENTITIES": [entity.value() for entity in state.visible_entities],
            "READS": [
                {"kind": read.kind, "content": read.content.value()}
                for read in state.reads
                if PROFILE_LEVEL[read.minimum_profile] <= PROFILE_LEVEL[self.profile]
            ],
        }
        reject_leakage(result)
        return result

    def serialize_state(self, state: SemanticState) -> str:
        return (
            f"[STPD_STATE version={SERIALIZER_VERSION} profile={self.profile}]\n"
            + canonical_json(self.state_content(state))
            + "\n[/STPD_STATE]"
        )

    def serialize_action(self, action: SemanticAction) -> str:
        value = action.semantic_dict()
        reject_leakage(value)
        return (
            f"[STPD_ACTION version={SERIALIZER_VERSION}]\n"
            + canonical_json(value)
            + "\n[/STPD_ACTION]"
        )

    def serialize(self, transition: ResearchTransitionV1) -> tuple[str, tuple[str, ...]]:
        if not transition.rank_eligible:
            raise BoundaryError("model_view", "transition_not_rank_eligible")
        return self.serialize_state(transition.state), tuple(
            self.serialize_action(action) for action in transition.actions
        )


def decision_fingerprint(transition: ResearchTransitionV1) -> str:
    """Group repeated decision inputs regardless of candidate order, label or runtime IDs."""
    serializer = FullRunSerializer("full")
    return semantic_hash(
        {
            "state": serializer.state_content(transition.state),
            "actions": sorted(serializer.serialize_action(a) for a in transition.actions),
        }
    )
