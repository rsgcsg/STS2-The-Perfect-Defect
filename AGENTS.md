# STPD Agent Guide

## Mission

Advance STPD as a reproducible research project without copying game authority into the
learner. Be explicit about what is implemented, measured, inferred, planned, or unknown.

## Required read order

Before editing:

1. `README.md`;
2. `docs/DOCUMENT_MAP.md`;
3. `docs/STATUS.md`;
4. `docs/memory/CURRENT.md` and `docs/memory/DECISIONS.md`;
5. the relevant canonical document;
6. the exact code and tests being changed.

Do not infer current state from a chat transcript or an old report when the repository
contains a newer exact source.

## Authority boundaries

- STS2 and the selected Host own game rules, RNG, effects, Commit, and successor truth.
- STS2-Connector owns the Host-neutral Player Environment contract.
- STPD owns research projection, serialization, datasets, labels, rewards, models,
  training, evaluation, and experiment bookkeeping.
- Never reconstruct legality, hidden state, or native operands in STPD.
- Never add Qwen-, reward-, tensor-, or policy-specific fields to Connector/Headless.
- A model may only choose from the current complete finite action catalog.

## Current code classification

The current `linear_q`, learner, contention, and Reference-transfer modules form the
**H1 integration/qualification lane**. They are not the final v0 model, but they are useful
and must remain runnable unless a reviewed migration includes compatibility imports and
replacement tests.

Do not rename or relocate them merely to make the tree look final.

## Work loop

For every coherent change:

1. pin the relevant source/data/model/Host identities;
2. identify the owning layer and smallest change;
3. add or update tests before claiming behavior;
4. run the smallest useful checks, then the integration checks required by the change;
5. record evidence and non-claims;
6. update canonical docs when behavior or status changes;
7. update the memory files for the next human or agent.

A failed gate is an engineering input, not permission to weaken the gate.

## Documentation and memory

- Canonical architecture/status/contract statements live under `docs/`.
- Working memory lives under `docs/memory/` and may not override canonical documents.
- Accepted long-lived decisions get an ADR under `docs/adr/` and an entry in
  `docs/memory/DECISIONS.md`.
- `docs/memory/CURRENT.md` is short and current; `HANDOFF.md` records the latest handoff;
  `OPEN_QUESTIONS.md` is the unresolved queue.
- Update links in `docs/DOCUMENT_MAP.md` when adding a canonical document.

## Code rules

- Python 3.11 from the locked `uv` environment; explicit type hints on public interfaces.
- Prefer `dataclass`, `TypedDict`, and `Protocol` at boundaries.
- Keep environment, data, representation, model, training, and evaluation concerns
  orthogonal.
- No module-level mutable experiment state.
- Determinism, seeds, revisions, and device/dtype are explicit configuration.
- Errors are typed or clearly classified; missing evidence fails closed.
- Model and dataset code must not depend on local paths, Steam IDs, or unversioned caches.
- Follow `docs/CODE_STYLE.md`.

## Data and model safety

Do not commit:

- proprietary game files, saves, raw Headless traces, or private identifiers;
- external datasets without clear redistribution rights;
- model weights, hidden-state caches, secrets, tokens, or service credentials;
- generated reports containing private paths or runtime identifiers.

Commit manifests, schemas, checksums, summaries, and reproducible commands instead.

## Test expectations

Pure repository checks must not require STS2 or proprietary files:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q stpd tests
```

Runtime/learner evidence is separate and must bind exact Headless, Connector, game,
model, dataset, and source identities. Never call a harness implementation a runtime pass.
