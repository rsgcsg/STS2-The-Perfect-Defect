"""Durable run reporting port; no central server or mutable latest-status authority."""

from __future__ import annotations

from typing import Protocol

from ..artifact_contracts import Manifest


class RunReporter(Protocol):
    def emit(self, event: Manifest) -> str: ...
    def completed(self, run_id: str) -> Manifest | None: ...
    def complete(self, result: Manifest) -> str: ...
    def events(self, run_id: str) -> tuple[Manifest, ...]: ...
