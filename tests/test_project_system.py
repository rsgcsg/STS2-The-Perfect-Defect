"""Mutation tests for the required cross-platform repository contract."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.project import CI_COMMAND, RepositoryGateError, portable_commands, validate_ci

ROOT = Path(__file__).resolve().parents[1]


def workflow() -> dict:
    return json.loads((ROOT / ".github/workflows/ci.yml").read_text())


def test_current_ci_contract() -> None:
    validate_ci(workflow())


@pytest.mark.parametrize("mutation", [
    "windows_subset", "skip_windows", "unpinned", "aggregate", "paths", "topic_push",
    "permissions", "credentials", "stale", "continue_on_error", "extra_job",
])
def test_ci_rejects_gate_weakening(mutation: str) -> None:
    value = copy.deepcopy(workflow())
    if mutation == "windows_subset":
        value["jobs"]["windows-portable"]["steps"][-1]["run"] = "uv run pytest tests/test_models.py"
    elif mutation == "skip_windows":
        value["jobs"]["windows-portable"]["if"] = "false"
    elif mutation == "unpinned":
        value["jobs"]["linux-portable"]["steps"][0]["uses"] = "actions/checkout@v4"
    elif mutation == "aggregate":
        value["jobs"]["locked-python"]["needs"] = ["linux-portable"]
    elif mutation == "paths":
        value["on"]["pull_request"] = {"paths": ["stpd/**"]}
    elif mutation == "topic_push":
        value["on"]["push"]["branches"].append("**")
    elif mutation == "permissions":
        value["permissions"]["contents"] = "write"
    elif mutation == "credentials":
        value["jobs"]["linux-portable"]["steps"][0]["with"]["persist-credentials"] = True
    elif mutation == "stale":
        value["concurrency"]["cancel-in-progress"] = False
    elif mutation == "continue_on_error":
        value["jobs"]["windows-portable"]["steps"][-1]["continue-on-error"] = True
    else:
        value["jobs"]["training"] = {"runs-on": "ubuntu-latest", "steps": []}
    with pytest.raises(RepositoryGateError):
        validate_ci(value)


def test_portable_gate_includes_all_existing_checks_and_package() -> None:
    commands = portable_commands("python")
    assert ("python", "tools/doctor.py") in commands
    assert ("python", "-m", "ruff", "check", ".") in commands
    assert ("python", "-m", "mypy", "stpd", "tools") in commands
    assert ("npm", "run", "check:connector-sdk") in commands
    assert ("python", "-m", "pytest", "-q") in commands
    assert ("python", "-m", "compileall", "-q", "stpd", "tests", "tools") in commands
    assert ("uv", "build") in commands
    assert ("git", "diff", "--check") in commands
    assert "project.py check" in CI_COMMAND


@pytest.mark.parametrize("mutation", ["python", "current", "bootstrap", "route", "eol"])
def test_repository_drift_is_rejected(tmp_path: Path, mutation: str) -> None:
    from tools.project import ROUTES, validate_repository

    for route in ROUTES:
        path = tmp_path / route
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Fixture\n")
    for path in ("AGENTS.md", "CONTRIBUTING.md"):
        (tmp_path / path).write_text("uv sync --locked --all-extras\ntools/project.py check\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.11,<3.12"\n')
    (tmp_path / ".python-version").write_text("3.11\n")
    (tmp_path / "uv.lock").write_text("fixture\n")
    (tmp_path / ".gitattributes").write_text("* text=auto eol=lf\n")
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".github/workflows/ci.yml").write_text(json.dumps(workflow()))
    validate_repository(tmp_path)
    if mutation == "python":
        (tmp_path / ".python-version").write_text("3.13\n")
    elif mutation == "current":
        (tmp_path / "docs/memory/CURRENT.md").write_text("x" * 3073)
    elif mutation == "bootstrap":
        (tmp_path / "AGENTS.md").write_text("python3 -m unittest\n")
    elif mutation == "route":
        (tmp_path / "README.md").write_text("[missing](absent.md)\n")
    else:
        (tmp_path / ".gitattributes").write_text("* text=auto\n")
    with pytest.raises(RepositoryGateError):
        validate_repository(tmp_path)
