# Project System

This document defines how humans and agents keep STPD understandable as code, data, models,
and evidence grow.

## Work lifecycle

```text
question
-> decision proposal or ADR
-> versioned interface/config
-> implementation + tests
-> experiment manifest
-> local run and raw evidence
-> reviewed report/checksums/non-claims
-> STATUS/ROADMAP update
-> memory handoff
```

A benchmark result without a manifest is exploratory. A document without matching code or
runtime evidence is not implementation evidence.

## Document management

- Every canonical document is linked from `DOCUMENT_MAP.md`.
- `STATUS.md` contains current facts, not future aspiration.
- `ROADMAP.md` contains ordered work and definitions of done.
- Interface changes update docs, schemas, tests, and dependent manifests together.
- Historical evidence is not rewritten; a new exact tuple gets a new report.
- Large research notes become dated plans or ADRs rather than expanding README indefinitely.

## Memory system

Humans and agents use the same files:

1. Read `memory/CURRENT.md`, `DECISIONS.md`, and `OPEN_QUESTIONS.md` before work.
2. During work, keep local scratch notes outside the repository.
3. At a coherent checkpoint, update `CURRENT.md` and `HANDOFF.md`.
4. Append accepted durable decisions to `DECISIONS.md`; create an ADR for architectural
   consequences.
5. Close or rewrite answered questions in `OPEN_QUESTIONS.md` with links to evidence.

Memory is concise and operational. It does not duplicate canonical architecture or status.

## Experiment identity

Use stable IDs such as:

```text
stpd-v0-s1-p-l-seed-0001
stpd-v0-s2-d-p-z-seed-0002
```

Each run records:

- STPD source revision and worktree state;
- plan/schema versions;
- data manifest digests;
- game/Host/Connector identities;
- Qwen model/tokenizer revisions, dtype, device, and cache mode;
- architecture/config ID and random seeds;
- output files and checksums;
- benchmark versions, metrics, and non-claims.

## Data and artifact storage

- Raw/external data and generated features stay in ignored local/object storage.
- Track dataset manifests, schema versions, licenses/usage constraints, and checksums.
- Model weights and Qwen hidden caches stay outside Git; track artifact manifests and hashes.
- Reports committed to the repository contain reviewed aggregate results, not private traces.

## Change and review rules

- One coherent responsibility per change.
- Public contract changes require migration notes.
- New model complexity requires a simpler baseline and a measurement plan.
- Evaluation code is reviewed independently from the model it evaluates when practical.
- Final Gold-test and fixed live suite remain sealed until architecture/input/hyperparameters
  are frozen.
- A failed hypothesis is retained as a result; do not tune the gate until it passes.
- Pull requests use `.github/pull_request_template.md` and the pure-Python CI must pass.
- Runtime/GPU experiments remain separate from CI and require exact local evidence.

## Continuous integration

GitHub Actions runs the pure suite on the single supported interpreter, Python 3.11:

```text
uv sync --frozen
-> ruff
-> mypy
-> pytest
-> package build
```

CI intentionally does not download STS2, Headless/Connector artifacts, Qwen weights, external
data, or GPU dependencies. A green CI run proves only the public source/test contract.

## Release states

- **pre-alpha**: interfaces and research system are changing; current state.
- **v0 candidate**: Step 0 contracts/data pipeline and core architecture implementation exist.
- **v0 frozen**: architecture/input/hyperparameters frozen before final held-out evaluation.
- **v0 complete**: B0-B7 report and next-phase decision published.

Version numbers do not imply policy quality or Host qualification.
