"""One-shot, exact-owned-branch preparation and reviewed provenance/pin repair."""
from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
BRANCH = "training/prefullrun/worker-evaluation-v1"
assert os.environ["GITHUB_REPOSITORY"] == "rsgcsg/STS2-The-Perfect-Defect"
assert os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH
assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == os.environ["GITHUB_SHA"]
assert not subprocess.check_output(["git", "status", "--porcelain"])

replacement = '''def _projections_from_manifests(store: ArtifactStore, records: tuple[ResearchTransitionV1, ...],
                               sources: tuple[Manifest, ...]) -> tuple[SourceProjection, ...]:
    from .fixtures import SyntheticSourceAdapter

    by_source = {source.payload("source").sha256: source for source in sources}
    if not sources or len(by_source) != len(sources):
        raise BoundaryError("dataset", "source_inventory_mismatch")
    if set(by_source) != {r.provenance.bundle_sha256 for r in records}:
        raise BoundaryError("dataset", "source_inventory_mismatch")
    projections = []
    for source_hash, source in by_source.items():
        info = source.parameters.value()
        if (source.kind != "evidence" or info.get("schema") != "stpd/source-projection-v1"
                or info.get("source_sha256") != source_hash):
            raise BoundaryError("dataset", "invalid_source_manifest")
        adapter = SyntheticSourceAdapter()
        if info.get("adapter") != adapter.adapter_id:
            raise BoundaryError("dataset", "final_platform_adapter_not_installed")
        payload = source.payload("source")
        if payload.size > 256 * 1024 * 1024:
            raise BoundaryError("dataset", "source_bundle_size_limit")
        projected = adapter.project(b"".join(store.read_payload(payload)))
        if (projected.source_sha256 != source_hash or projected.scope != info.get("scope")
                or projected.run_proofs.value() != info.get("run_proofs")):
            raise BoundaryError("dataset", "source_attestation_mismatch")
        expected = {record.transition_id: record.to_dict() for record in projected.transitions}
        actual = {record.transition_id: record.to_dict() for record in records
                  if record.provenance.bundle_sha256 == source_hash}
        if actual != expected:
            raise BoundaryError("dataset", "source_transition_projection_mismatch")
        projections.append(projected)
    return tuple(projections)
'''
path = Path("stpd/fullrun/data.py")
source = path.read_text(encoding="utf-8")
function = next(node for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef) and node.name == "_projections_from_manifests")
lines = source.splitlines(keepends=True)
source = "".join(lines[:function.lineno - 1]) + replacement + "".join(lines[function.end_lineno:])
for argument in ("dataset.records", "tuple(records)"):
    pattern = r"_projections_from_manifests\(\s*" + re.escape(argument) + r",\s*sources\s*\)"
    source, count = re.subn(pattern, f"_projections_from_manifests(store, {argument}, sources)", source)
    assert count == 1
marker = "        if any(record.terminal for record in run[:-1]):"
assert source.count(marker) == 1
source = source.replace(marker, '        if not run[-1].terminal:\n'
                        '            raise BoundaryError("admission", "missing_terminal_disposition")\n' + marker)
path.write_text(source, encoding="utf-8", newline="\n")
test_path = Path("tests/test_fullrun_admission.py")
test_source = test_path.read_text(encoding="utf-8")
assert "test_new_dataset_identity_cannot_relabel_an_unchanged_source" not in test_source
test_source += '''

def test_new_dataset_identity_cannot_relabel_an_unchanged_source(tmp_path: Path) -> None:
    from test_artifact_store_v1 import PRODUCER, store

    target = store(tmp_path)
    source, projected = publish_source(target, synthetic_bundle(runs=6), SyntheticSourceAdapter(), PRODUCER)
    changed = replace(projected.transitions[0], chosen_key=projected.transitions[0].actions[0].key)
    forged = admit((replace(projected, transitions=(changed, *projected.transitions[1:])),))
    with pytest.raises(BoundaryError, match="source_transition_projection_mismatch"):
        publish_dataset(target, forged, (source,), PRODUCER)
'''
test_path.write_text(test_source, encoding="utf-8", newline="\n")
paths = ["stpd/fullrun/features.py", "stpd/fullrun/evaluation.py", "stpd/fullrun/data.py",
         "stpd/models/scheme1.py", "stpd/storage/run_reporter.py",
         *[str(p) for p in sorted(Path("stpd/workers").glob("*.py"))],
         "tests/test_fullrun_features.py", "tests/test_checkpoint_codec.py",
         "tests/test_fullrun_evaluation.py", "tests/test_run_reporter.py",
         "tests/test_fullrun_worker.py", "tests/test_fullrun_admission.py"]
subprocess.run(["uv", "run", "--locked", "ruff", "check", "--fix", *paths], check=False)
subprocess.run(["uv", "run", "--locked", "ruff", "format", *paths], check=True)
# Re-pin only the reviewed source closure; previous runtime evidence does not transfer.
adapter_ast = ast.parse(Path("stpd/policy/adapter.py").read_text(encoding="utf-8"))
closure = next(ast.literal_eval(node.value) for node in adapter_ast.body
               if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
               and target.id == "ADAPTER_SOURCE_CLOSURE" for target in node.targets))
files = [{"path": name, "sha256": hashlib.sha256(Path(name).read_bytes()).hexdigest()} for name in closure]
code_sha = hashlib.sha256(json.dumps(files, ensure_ascii=False, allow_nan=False,
                                     sort_keys=True, separators=(",", ":")).encode()).hexdigest()
policy_paths = []
for version in ("v2", "v3"):
    policy = Path(f"policy-manifests/s1-policy-adapter-{version}.json")
    value = json.loads(policy.read_text(encoding="utf-8"))
    assert value["adapter"]["code_sha256"] == "607b108f81cabc9721f9debd3d3a6c1e79f4e5a4bff8eba85308a2382fb74dfe"
    value["adapter"]["code_sha256"] = code_sha
    value["manifest_id"] += "-shared-head-" + code_sha[:12]
    policy.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
    policy_paths.append(str(policy))
map_path = Path("docs/DOCUMENT_MAP.md")
original = map_path.read_text(encoding="utf-8")
assert "FULLRUN_TRAINING.md" not in original
map_path.write_text(original.rstrip() + "\n\n[Full-Run Training](FULLRUN_TRAINING.md)\n",
                    encoding="utf-8", newline="\n")
# Self-removal precedes full source checks, so temporary executor code is not product code.
Path(".github/workflows/prefullrun-worker-once.yml").unlink()
Path(__file__).unlink()
checks = {}
for name, command in {
    "ruff": ["uv", "run", "--locked", "ruff", "check", "."],
    "mypy": ["uv", "run", "--locked", "mypy", "stpd", "tools"],
    "focused_pytest": ["uv", "run", "--locked", "pytest", "-q", *[p for p in paths if p.startswith("tests/")]],
}.items():
    checks[name] = subprocess.run(command, check=False).returncode
report = {"input_head": os.environ["GITHUB_SHA"], "policy_code_sha256": code_sha,
          "focused_uncommitted_checks": checks,
          "non_claims": ["latest-head full CI", "Windows", "runtime transfer", "scientific result",
                         "pre-Full-Run program readiness"]}
evidence = Path("docs/evidence/WORKER_BOOTSTRAP_2026-09-06.md")
evidence.write_text("# Worker bootstrap\n\nSource-generation receipt, not final current-head CI.\n\n```json\n"
                    + json.dumps(report, indent=2) + "\n```\n", encoding="utf-8", newline="\n")
allowed = set(paths + policy_paths) | {"docs/DOCUMENT_MAP.md", str(evidence),
                                       ".github/workflows/prefullrun-worker-once.yml",
                                       "tools/prefullrun_worker_once.py"}
changed = set(subprocess.check_output(["git", "diff", "--name-only"], text=True).splitlines())
untracked = set(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], text=True).splitlines())
assert changed | untracked <= allowed
subprocess.run(["git", "diff", "--check"], check=True)
subprocess.run(["git", "add", "-A", "--", *sorted(allowed)], check=True)
subprocess.run(["git", "-c", "user.name=STPD Engineering Automation", "-c",
                "user.email=stpd-engineering@users.noreply.github.com", "commit", "-m",
                "test(training): verify provenance, recovery and shared-head source identity"], check=True)
header = "AUTHORIZATION: basic " + base64.b64encode(
    ("x-access-token:" + os.environ["STPD_SOURCE_TOKEN"]).encode()).decode()
auth = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
            GIT_CONFIG_VALUE_0=header)
remote = subprocess.check_output(["git", "ls-remote", "--exit-code", "origin", "refs/heads/" + BRANCH],
                                  env=auth, text=True).split()[0]
assert remote == os.environ["GITHUB_SHA"], "remote moved: refuse overwrite"
subprocess.run(["git", "push", "origin", "HEAD:refs/heads/" + BRANCH], env=auth, check=True)
raise SystemExit(1 if any(checks.values()) else 0)
