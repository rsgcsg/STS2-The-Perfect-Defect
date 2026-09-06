# Contributing

STPD is pre-alpha and evidence-first. Read [Development Workflow](docs/DEVELOPMENT_WORKFLOW.md),
[Engineering Governance](docs/ENGINEERING_GOVERNANCE.md), and the owning contract before editing.
Normal changes start from exact current develop and use a short-lived topic PR. Never
force-push or directly update protected branches. The historical H1/combat-v0 lanes remain
reproducible; a new Full-Run contract does not silently redefine them.

## Setup and checks

Python >=3.11,<3.12 and uv.lock define the only supported developer environment:

```bash
uv sync --locked --all-extras
npm ci
uv run --locked python tools/project.py context
uv run --locked python tools/project.py check
uv run --locked python tools/project.py closeout
```

The same root gate runs on Linux and Windows. Cold dependency provisioning can require
network; tests need no game, Human corpus, Qwen weights, GPU, or production credentials.
[Testing](docs/TESTING.md) distinguishes local checks, CI and real-world evidence.

## Changes and review

Identify one primary owner: contract, environment adapter, data, representation, model,
training, evaluation, qualification, or operations. Keep structural refactors separate from
scientific experiments. Prefer the smallest clean causal design, not a tiny diff that leaves
a broken abstraction in place. Public contracts are typed and have positive, negative,
tamper, identity-drift and recovery tests where applicable.

Platform owns game/environment authority. STPD consumes exact public releases or explicitly
non-stable candidates; it does not reconstruct legality, Commit, successor, or Human/native
correlation. Keep runtime IDs and future information out of model features.

PRs bind exact base/head, owner, change class, failure model, tests, identity impact, rollback,
merge method and non-claims. Update canonical documents, DOCUMENT_MAP and bounded memory when
facts change. Required checks and review conditions apply at the latest head. Topic squash
merge is normal; source-bound runtime/scientific evidence does not automatically transfer.

Do not commit raw/private data, proprietary files, model weights, credentials, caches or large
outputs. Store artifacts outside Git and record immutable manifests/checksums. Failed runs
remain failed evidence. A passing test or completed training run is not model-quality proof.
