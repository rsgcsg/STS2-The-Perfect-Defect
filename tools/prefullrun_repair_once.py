"""One-shot, exact-branch source repair; removed in its own resulting commit."""
from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
BRANCH = "ops/governance/prefullrun-v2"
assert os.environ["GITHUB_REPOSITORY"] == "rsgcsg/STS2-The-Perfect-Defect"
assert os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH
assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == os.environ["GITHUB_SHA"]
assert not subprocess.check_output(["git", "status", "--porcelain"])


def replace_once(path: Path, before: str, after: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(before) == 1, f"repair precondition failed: {path}"
    path.write_text(text.replace(before, after), encoding="utf-8", newline="\n")


def explicit_lf_writes(path: Path) -> None:
    """Insert an explicit newline argument only on write_text calls, not reads."""
    source = path.read_bytes()
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    inserts = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "write_text" or any(k.arg == "newline" for k in node.keywords):
            continue
        encoding = next((k for k in node.keywords if k.arg == "encoding"), None)
        assert encoding is not None and encoding.end_lineno is not None
        assert encoding.end_col_offset is not None
        inserts.append(offsets[encoding.end_lineno - 1] + encoding.end_col_offset)
    assert inserts, f"no text writers found: {path}"
    for offset in sorted(inserts, reverse=True):
        source = source[:offset] + b', newline="\\n"' + source[offset:]
    ast.parse(source)
    path.write_bytes(source)


handoff = ROOT / "stpd/data/training_handoff.py"
replace_once(handoff, "from pathlib import Path\n", "from pathlib import Path, PurePosixPath\n")
replace_once(handoff, "prefix = str(Path(manifest_logical).parent)",
             "prefix = PurePosixPath(manifest_logical).parent.as_posix()")
for relative in ("stpd/data/training_handoff.py", "stpd/qwen/feature_artifact.py",
                 "tests/test_human_evidence_v2.py"):
    explicit_lf_writes(ROOT / relative)

# Recompute the exact reviewed runtime source closure without executing model code.
source = ast.parse((ROOT / "stpd/policy/adapter.py").read_text(encoding="utf-8"))
closure = next(ast.literal_eval(node.value) for node in source.body
               if isinstance(node, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "ADAPTER_SOURCE_CLOSURE"
                       for t in node.targets))
files = [{"path": name, "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
         for name in closure]
encoded = json.dumps(files, ensure_ascii=False, allow_nan=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
digest = hashlib.sha256(encoded).hexdigest()
assert digest == "607b108f81cabc9721f9debd3d3a6c1e79f4e5a4bff8eba85308a2382fb74dfe"
for version in ("v2", "v3"):
    path = ROOT / f"policy-manifests/s1-policy-adapter-{version}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["adapter"]["code_sha256"] == "708b5b1efaafb0395702b866441d2753584f3cb0b0f410b23205f4b5a9fc840c"
    value["adapter"]["code_sha256"] = digest
    value["manifest_id"] += "-portable-" + digest[:12]
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")

# Only our transient executor files are removed, never prior repository/user files.
(ROOT / ".github/workflows/prefullrun-repair-once.yml").unlink()
Path(__file__).unlink()
allowed = {"stpd/data/training_handoff.py", "stpd/qwen/feature_artifact.py",
           "tests/test_human_evidence_v2.py", "policy-manifests/s1-policy-adapter-v2.json",
           "policy-manifests/s1-policy-adapter-v3.json",
           ".github/workflows/prefullrun-repair-once.yml", "tools/prefullrun_repair_once.py"}
changed = set(subprocess.check_output(["git", "diff", "--name-only"], text=True).splitlines())
assert changed == allowed, f"unexpected repair file set: {sorted(changed)}"
# Ruff fixes only line wrapping introduced by the explicit keyword, never removes a check.
subprocess.run(["uv", "run", "--locked", "ruff", "format", "stpd/data/training_handoff.py",
                "stpd/qwen/feature_artifact.py", "tests/test_human_evidence_v2.py"], check=True)
subprocess.run(["git", "diff", "--check"], check=True)
subprocess.run(["git", "add", "--", *sorted(allowed)], check=True)
subprocess.run(["git", "-c", "user.name=STPD Engineering Automation", "-c",
                "user.email=stpd-engineering@users.noreply.github.com", "commit", "-m",
                "fix(portability): preserve POSIX logical paths and exact LF artifact bytes"], check=True)
header = "AUTHORIZATION: basic " + base64.b64encode(
    ("x-access-token:" + os.environ["STPD_REPAIR_TOKEN"]).encode()).decode()
auth = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
            GIT_CONFIG_VALUE_0=header)
remote = subprocess.check_output(["git", "ls-remote", "--exit-code", "origin",
                                  "refs/heads/" + BRANCH], env=auth, text=True).split()[0]
assert remote == os.environ["GITHUB_SHA"], "remote moved: refusing concurrent overwrite"
subprocess.run(["git", "push", "origin", "HEAD:refs/heads/" + BRANCH], env=auth, check=True)
print("Preserved exact source repair; full current-head portable CI is still required.")
