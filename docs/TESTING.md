# Testing and Evidence

## Supported portable contract

Bootstrap once with `uv sync --locked --all-extras` and `npm ci`, then:

```bash
uv run --locked python tools/project.py check
uv run --locked python tools/project.py closeout --base <exact-base-sha>
```

Python >=3.11,<3.12 is required. Dependencies may need network on a cold cache. Tests do not
require STS2, proprietary binaries, real Human evidence, Qwen weights, GPU or production
credentials. Installed versioned Platform consumer packages are checked; they are not a
real-game installation. The lock may include GPU-capable framework wheels, but CI never
requires GPU hardware or downloads model weights.

The root gate validates repository/CI contracts, runs tools/doctor.py, Ruff on the whole tree,
Mypy on stpd/tools, the existing Connector SDK test, the complete Pytest suite, compileall,
`uv build`, working-tree and HEAD patch hygiene, and optional exact-base diff hygiene.
Focused tests accelerate development but never replace this gate.

Linux-portable and Windows-portable run the identical command. Required locked-python is
successful only when both succeed. Exact head checkout, read-only permissions, immutable
Action pins and stale-run cancellation are checked structurally. Do not weaken a check to
repair CI. A green result on an older SHA is not current-head evidence.

## Test shapes

Contracts: valid, malformed, future schema, missing provenance, tampered bytes, collisions,
duplicates, stale inputs and identity drift. Data: candidate completeness, whole-run and
semantic-component isolation, deduplication and leakage. Artifacts: immutable/idempotent
publication, integrity, missing objects, publication interruption, deterministic registry
rebuild and lineage. Workers: input verification, durable checkpoint, crash/resume, duplicate
completion, reporting failure and provider neutrality. Models: one score per candidate,
permutation behavior, finite loss, frozen backbone, Linear/MLP and checkpoint round trips.

Use FakeQwen, CPU and deterministic synthetic fixtures in portable tests. Provider-specific
integration is opt-in. Local/fake conformance is not real S3 or cloud qualification.

## Evidence boundaries

Source/test/package, data admission, model artifacts, training, offline/Gold/live evaluation,
scientific inference and service deployment are separate dimensions. A fixture E2E is only
engineering evidence. A completed GPU run does not prove quality; a green build does not prove
real-game qualification. Record source, command, environment, input/artifact identities,
results and non-claims. Never transfer evidence across changed identities without proof.
