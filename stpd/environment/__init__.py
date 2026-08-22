"""Player Environment projection and stable-transition collection."""

from .collector import CollectedTransition, CollectionError, StableTransitionCollector
from .identity import MANAGED_DRIVER_PROTOCOL, environment_identity_from_managed_ready
from .projector import ProjectedDecision, ResearchProjectorV0
from .runtime_collection import RuntimeCollection, collect_managed_runtime, token_profile_records

__all__ = [
    "CollectionError",
    "CollectedTransition",
    "MANAGED_DRIVER_PROTOCOL",
    "ProjectedDecision",
    "ResearchProjectorV0",
    "RuntimeCollection",
    "StableTransitionCollector",
    "environment_identity_from_managed_ready",
    "collect_managed_runtime",
    "token_profile_records",
]
