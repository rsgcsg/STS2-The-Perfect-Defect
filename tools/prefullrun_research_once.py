"""Exact-branch, self-removing source preparation; no qualification or gate bypass."""
from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
BRANCH = "data/prefullrun/research-core-v1"
assert os.environ["GITHUB_REPOSITORY"] == "rsgcsg/STS2-The-Perfect-Defect"
assert os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH
assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == os.environ["GITHUB_SHA"]
assert not subprocess.check_output(["git", "status", "--porcelain"])
path = Path("stpd/fullrun/contracts.py")
text = path.read_text(encoding="utf-8")
marker = "        for transition in self.transitions:\n"
assert text.count(marker) == 1
validation = '''        for run_id, value in self.run_proofs.value().items():
            text(run_id, "projection.run_id")
            proof = object_fields(value, {"started_ref", "terminal_ref", "record_count"},
                                  "projection.run_proof")
            digest(proof["started_ref"], "projection.run_start")
            digest(proof["terminal_ref"], "projection.run_terminal")
            unsigned(proof["record_count"], "projection.record_count")
'''
path.write_text(text.replace(marker, validation + marker), encoding="utf-8", newline="\n")
paths = [str(p) for p in sorted(Path("stpd/fullrun").glob("*.py"))] + [
    "tests/test_fullrun_contracts.py", "tests/test_fullrun_admission.py"]
subprocess.run(["uv", "run", "--locked", "ruff", "check", "--fix", *paths], check=False)
subprocess.run(["uv", "run", "--locked", "ruff", "format", *paths], check=True)
checks = {}
for name, command in {
    "focused_ruff": ["uv", "run", "--locked", "ruff", "check", *paths],
    "focused_pytest": ["uv", "run", "--locked", "pytest", "-q", "tests/test_fullrun_contracts.py",
                       "tests/test_fullrun_admission.py"],
    "mypy": ["uv", "run", "--locked", "mypy", "stpd", "tools"],
}.items():
    checks[name] = subprocess.run(command, check=False).returncode
map_path = Path("docs/DOCUMENT_MAP.md")
original = map_path.read_text(encoding="utf-8")
assert "FULLRUN_RESEARCH.md" not in original
map_path.write_text(original.rstrip() + "\n\n[Full-Run Research](FULLRUN_RESEARCH.md)\n",
                    encoding="utf-8", newline="\n")
evidence = Path("docs/evidence/FULLRUN_CONTRACT_BOOTSTRAP_2026-09-06.md")
evidence.write_text("# Full-Run contract bootstrap\n\nSource-generation receipt; not final CI.\n\n```json\n"
                    + json.dumps({"input_head": os.environ["GITHUB_SHA"],
                                  "focused_uncommitted_checks": checks,
                                  "non_claims": ["latest-head CI", "Windows", "Platform qualification",
                                                 "scientific evidence", "program readiness"]}, indent=2)
                    + "\n```\n", encoding="utf-8", newline="\n")
Path(".github/workflows/prefullrun-research-once.yml").unlink()
Path(__file__).unlink()
allowed = set(paths) | {"docs/DOCUMENT_MAP.md", str(evidence),
                       ".github/workflows/prefullrun-research-once.yml",
                       "tools/prefullrun_research_once.py"}
changed = set(subprocess.check_output(["git", "diff", "--name-only"], text=True).splitlines())
untracked = set(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"],
                                        text=True).splitlines())
assert changed | untracked <= allowed
subprocess.run(["git", "diff", "--check"], check=True)
subprocess.run(["git", "add", "-A", "--", *sorted(allowed)], check=True)
subprocess.run(["git", "-c", "user.name=STPD Engineering Automation", "-c",
                "user.email=stpd-engineering@users.noreply.github.com", "commit", "-m",
                "test(fullrun): validate source proofs and prepare deterministic research contracts"],
               check=True)
header = "AUTHORIZATION: basic " + base64.b64encode(
    ("x-access-token:" + os.environ["STPD_SOURCE_TOKEN"]).encode()).decode()
auth = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
            GIT_CONFIG_VALUE_0=header)
remote = subprocess.check_output(["git", "ls-remote", "--exit-code", "origin", "refs/heads/" + BRANCH],
                                  env=auth, text=True).split()[0]
assert remote == os.environ["GITHUB_SHA"], "concurrent head change: refuse overwrite"
subprocess.run(["git", "push", "origin", "HEAD:refs/heads/" + BRANCH], env=auth, check=True)
print("Reviewed file set persisted; fresh full current-head CI remains required.")
raise SystemExit(1 if any(checks.values()) else 0)
