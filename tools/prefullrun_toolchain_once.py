"""One-shot locked dependency generation on one owned branch; self-removing."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
BRANCH = "data/prefullrun/artifact-foundation-v1"
assert os.environ["GITHUB_REPOSITORY"] == "rsgcsg/STS2-The-Perfect-Defect"
assert os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH
assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == os.environ["GITHUB_SHA"]
assert not subprocess.check_output(["git", "status", "--porcelain"])


def package_pins(document: dict) -> set[tuple[str, str, str]]:
    return {(p["name"], p.get("version", ""), json.dumps(p.get("source"), sort_keys=True))
            for p in document["package"] if p["name"] != "sts2-the-perfect-defect"}


old = package_pins(tomllib.loads(Path("uv.lock").read_text()))
project_path = Path("pyproject.toml")
project = project_path.read_text(encoding="utf-8")
parsed = tomllib.loads(project)
assert parsed["project"]["requires-python"] == ">=3.11,<3.12"
assert "research" not in parsed["project"]["optional-dependencies"]
marker = "[project.optional-dependencies]\n"
assert project.count(marker) == 1
project = project.replace(marker, marker + 'research = [\n  "boto3>=1.35,<2",\n  "duckdb>=1.4,<2",\n]\n')
project += '\n[[tool.mypy.overrides]]\nmodule = ["boto3", "botocore", "botocore.*"]\nignore_missing_imports = true\n'
project_path.write_text(project, encoding="utf-8", newline="\n")
subprocess.run(["uv", "lock"], check=True)
new = package_pins(tomllib.loads(Path("uv.lock").read_text()))
assert old <= new, "an existing dependency pin changed; refuse implicit upgrade"
subprocess.run(["uv", "sync", "--locked", "--all-extras"], check=True)

paths = ["stpd/json_boundary.py", "stpd/artifact_contracts.py", "stpd/storage/__init__.py",
         "stpd/storage/blobs.py", "stpd/storage/local.py", "stpd/storage/store.py",
         "stpd/storage/s3.py", "stpd/storage/registry.py", "tests/test_artifact_store_v1.py",
         "tests/test_storage_adapters_v1.py"]
subprocess.run(["uv", "run", "--locked", "ruff", "check", "--fix", *paths], check=False)
subprocess.run(["uv", "run", "--locked", "ruff", "format", *paths], check=True)
checks = {}
for name, command in {
    "focused_ruff": ["uv", "run", "--locked", "ruff", "check", *paths],
    "focused_pytest": ["uv", "run", "--locked", "pytest", "-q", "tests/test_artifact_store_v1.py",
                       "tests/test_storage_adapters_v1.py"],
}.items():
    checks[name] = subprocess.run(command, check=False).returncode

for relative, link in [
    ("docs/DOCUMENT_MAP.md", "[Local-First manifest ADR](adr/0003-local-first-manifest-research.md)"),
    ("docs/adr/README.md", "[ADR-0003: Local-First manifest research](0003-local-first-manifest-research.md)"),
]:
    path = Path(relative)
    before = path.read_text(encoding="utf-8")
    assert "0003-local-first-manifest-research.md" not in before
    path.write_text(before.rstrip() + "\n\n" + link + "\n", encoding="utf-8", newline="\n")
report = {
    "schema": "stpd/bootstrap-source-evidence-v1", "input_head": os.environ["GITHUB_SHA"],
    "existing_dependency_pins_preserved": True,
    "added_dependencies": sorted(new - old),
    "uv_lock_sha256": hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest(),
    "focused_checks_on_uncommitted_worktree": checks,
    "non_claims": ["latest-head full CI", "Windows", "real S3", "pre-Full-Run readiness"],
}
evidence = Path("docs/evidence/ARTIFACT_FOUNDATION_BOOTSTRAP_2026-09-06.md")
evidence.write_text("# Artifact foundation bootstrap\n\n"
                    "This is a source-generation receipt, not final CI or readiness evidence.\n\n"
                    "```json\n" + json.dumps(report, indent=2) + "\n```\n",
                    encoding="utf-8", newline="\n")
Path(".github/workflows/prefullrun-toolchain-once.yml").unlink()
Path(__file__).unlink()
allowed = set(paths) | {"pyproject.toml", "uv.lock", "docs/DOCUMENT_MAP.md", "docs/adr/README.md",
                       str(evidence), ".github/workflows/prefullrun-toolchain-once.yml",
                       "tools/prefullrun_toolchain_once.py"}
changed = set(subprocess.check_output(["git", "diff", "--name-only"], text=True).splitlines())
untracked = set(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"],
                                        text=True).splitlines())
assert changed | untracked <= allowed, "unexpected file change; refuse publication"
subprocess.run(["git", "diff", "--check"], check=True)
subprocess.run(["git", "add", "-A", "--", *sorted(allowed)], check=True)
subprocess.run(["git", "-c", "user.name=STPD Engineering Automation", "-c",
                "user.email=stpd-engineering@users.noreply.github.com", "commit", "-m",
                "build(research): lock S3 and analysis dependencies without upgrading existing pins"],
               check=True)
header = "AUTHORIZATION: basic " + base64.b64encode(
    ("x-access-token:" + os.environ["STPD_TOOLCHAIN_TOKEN"]).encode()).decode()
auth = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
            GIT_CONFIG_VALUE_0=header)
remote = subprocess.check_output(["git", "ls-remote", "--exit-code", "origin",
                                  "refs/heads/" + BRANCH], env=auth, text=True).split()[0]
assert remote == os.environ["GITHUB_SHA"], "remote moved: refusing overwrite"
subprocess.run(["git", "push", "origin", "HEAD:refs/heads/" + BRANCH], env=auth, check=True)
print("Exact lock and source persisted; complete latest-head portable CI remains required.")
raise SystemExit(1 if any(checks.values()) else 0)
