"""Developer operations and read-only research projections over owning services.

Training, evaluation, recording and admission authority stay in their components.
Projection exports load on use so project setup needs only the Python standard library.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .analysis import AnalysisReport, analyze
    from .dashboard import DashboardProjection, project, render_html

__all__ = ["AnalysisReport", "DashboardProjection", "analyze", "project", "render_html"]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    module = ".analysis" if name in {"AnalysisReport", "analyze"} else ".dashboard"
    return getattr(import_module(module, __name__), name)
