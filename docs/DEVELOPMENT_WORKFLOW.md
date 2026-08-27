# STPD Development Workflow

This document governs Git collaboration and releases for the STPD research
repository.

## Position in the project system

```text
STS2 AI Platform
├── Platform Foundation
│   └── shared environment, annotation, evidence and policy-delivery contracts
└── Research Projects
    └── STPD (this repository)
        └── data, representation, model, training, evaluation and experiments
```

STPD is an independent research project built on the upper-level Platform
Foundation. Its independent repository, versions and release cycle isolate
research work; they do not make STPD a peer platform. STPD consumes only public,
versioned Platform contracts and exact release/candidate identities. It never
owns game truth, legality, native execution, Receipt or successor truth.

Platform remains model-neutral and does not depend on STPD checkpoints,
rewards, training or research projections.

## Governance migration

Public `main` commit
`4c4bbca5e5bf16656bd7c0ba175ff5c069c81818` is preserved as
`baseline/pre-governance-stpd-20260827`. It is a green historical integration
snapshot, not a stable research release. No history was rewritten.

`develop` was created from that exact commit. Normal work now targets
`develop`. The first governed release follows:

```text
develop -> release/<version> -> release gates -> main -> version tag
```

Only after this transition does `main` mean stable within the release's
declared research and engineering scope. Stable never means model-optimal or
scientifically qualified unless a separate report proves that claim.

## Branches and PRs

- `main`: governed research releases and urgent `hotfix/*` only.
- `develop`: the single long-lived integration line and normal PR target.
- `contract|environment|data|representation|model|training|evaluation|qualification|policy|docs|ops|experiment/<scope>/<name>`:
  short-lived topic branches from current `develop`.
- `release/<version>`: stabilization, provenance, versioning and release notes.
- `hotfix/<name>`: urgent fix from `main`, then merged back into `develop`.

Do not create permanent model/component develop branches. Prefer one coherent,
self-contained responsibility per PR and squash topic PRs. Separate structural
refactors from behavior or experiment changes when either is substantial.

Before editing, fetch/prune, inspect `origin/develop`, active PRs and exact base
SHA, then create one branch/worktree per human or agent. A handoff records repo,
branch, base/HEAD SHAs, task/non-goals, files, checks, pending work and risks.
Do not overwrite new manifests, experiment configs or provenance from a stale
branch.

Every PR records base branch/SHA, workstream, owner, scope, non-goals,
cross-repository dependency, exact source/data/model/Platform identity,
evidence level, rollback and non-claims. A green pure CI run is source/test
evidence only; it is not GPU, runtime, model-quality or scientific evidence.

## Platform dependency

STPD may consume:

1. an immutable Platform release/package; or
2. an unreleased integration candidate pinned by exact SHA, artifact/package
   digest, protocol and manifest and explicitly labelled non-stable.

Floating `Platform/develop`, sibling-source imports and unversioned local
artifacts are forbidden production/research dependencies. Cross-repository work
uses separate PRs:

```text
Platform candidate and exact identity
  -> STPD manifest/config pin
  -> adapter, admission and experiment verification
```

Platform `successor_not_stable` is owned by a Platform Policy Runtime branch;
it is not a reason to change the frozen STPD checkpoint or Qwen semantics.
Human semantic schema-2 closeout is a separate Platform evidence branch.

## Research evidence and release

Pure checks run without STS2, proprietary files, Qwen weights, GPU, network or
private data:

```bash
uv sync --locked --all-extras
npm ci
uv run ruff check .
uv run mypy stpd
uv run pytest -q
git diff --check
```

Runtime/GPU/data/model evidence binds exact STPD source, Platform release or
candidate, game/Host/Connector identity, dataset/model manifests, seeds and
artifact checksums. Raw data, weights, caches, credentials and private traces
stay outside Git. Failed experiments remain failed evidence; do not weaken a
gate or edit raw evidence.

A release branch may fix release blockers and update versions, manifests,
reviewed reports and docs. It may not introduce a new model architecture or
experiment. Merge it to `main`, tag it, then synchronize stabilization changes
back to `develop`.

## GitHub enforcement

Both `main` and `develop` should require pull requests, the `locked-python`
status check and resolved conversations, and block deletion and force pushes.
Approval requirements can increase when another qualified reviewer is
available; administrator bypass is not the normal workflow. Actual GitHub
settings are operational evidence and must be inspected before claiming they
are enabled.

This workflow combines short-lived, self-contained changes with one integration
line and explicit release stabilization. It uses only the useful release
isolation ideas from GitFlow rather than adopting its long-lived feature model.
See [GitHub PR standardization](https://docs.github.com/en/pull-requests/reference/managing-and-standardizing-pull-requests),
[short-lived feature branches](https://trunkbaseddevelopment.com/short-lived-feature-branches/)
and [Google's small-change guidance](https://google.github.io/eng-practices/review/developer/small-cls.html).
