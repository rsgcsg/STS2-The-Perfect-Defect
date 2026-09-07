# Project System

STPD is an independently governed research consumer of model-neutral STS2 AI Platform.
See [Development Workflow](DEVELOPMENT_WORKFLOW.md) for branch/release policy and
[Engineering Governance](ENGINEERING_GOVERNANCE.md) for authority and evidence classes.

## Entry and work loop

README -> [New Engineer Guide](NEW_ENGINEER_GUIDE.md) -> AGENTS -> project context ->
[Document Map](DOCUMENT_MAP.md) -> owning contract, exact source and tests.

```bash
uv sync --locked --all-extras
npm ci
uv run --locked python tools/project.py context
uv run --locked python tools/project.py check
uv run --locked python tools/project.py closeout
```

Context is read-only routing. Check runs structural governance validation, package doctor,
Ruff, Mypy, SDK check, Pytest, compileall, package build and patch hygiene. Closeout runs the
same gate and reports exact local source plus dirty status. Neither command declares runtime,
scientific, cross-platform CI or pre-Full-Run readiness. See [Testing](TESTING.md).

Both CI operating systems execute the same root command. The required locked-python job
aggregates both and rejects failure/cancellation/skipping. Workflow JSON is a YAML-compatible
subset that permits structural validation using only the Python standard library. Tests
mutate the workflow to prove that common weakening attempts are rejected.

## Documents and memory

Canonical docs are linked from DOCUMENT_MAP; STATUS contains supported current facts,
ROADMAP ordered goals, ADRs accepted architecture. A proposal does not prove implementation.
Current context is at most 3 KiB: phase, active lanes, blockers, next gates, non-goals, pointers.
Detailed evidence belongs in immutable manifests/reports or dated archives, not CURRENT.
Append decisions instead of rewriting history. Update HANDOFF at meaningful checkpoints.

Question -> owning fact -> contract/design -> implementation/test -> review/repair -> exact
commit/PR -> evidence/docs -> next task. Use one branch/worktree per writer. Persist useful
work remotely rather than leaving it in ephemeral execution storage.

## Research identity and release

Runs bind source/worktree state, protocol/config, data/Qwen/tokenizer/serializer identities,
seeds, dtype/device and output hashes. Benchmark results without manifests are exploratory.
Keep raw data/weights/caches outside Git. Failure evidence remains retained. Sealed Gold-test
and final live suites are not used before the relevant protocol freeze.

The pre-governance main at 4c4bbca5e5bf16656bd7c0ba175ff5c069c81818 is historical, not a stable
research release. develop is the integration line; governed release branches land on main.
Version/release labels never imply policy quality. Historical v0 maturity and new Full-Run
engineering readiness are distinct, independently evidenced concepts.
