"""Local-first analysis and dashboard projections.

The workbench is deliberately a read-only consumer of the durable artifact and
registry interfaces.  It does not define training, evaluation, or admission
authority.
"""

from .analysis import AnalysisReport, analyze
from .dashboard import DashboardProjection, project, render_html

__all__ = [
    "AnalysisReport",
    "DashboardProjection",
    "analyze",
    "project",
    "render_html",
]
