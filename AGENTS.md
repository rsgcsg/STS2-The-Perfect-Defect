# STPD Agent Guide

## Mission and authority

Advance reproducible research. Distinguish implementation, tests, measurements, proposals,
and unknowns. Platform is the model-neutral environment foundation; STPD is the independently
governed research consumer. STS2/Host and Platform own rules, RNG, legality, native execution,
Commit, Human/native correlation, semantic state and causal successor truth. STPD owns research
projection, datasets, model representation, training, evaluation, and scientific provenance.

Preserve `H != S` and `A_public != A_sem(S)`. Never reconstruct missing native authority in STPD.
A model chooses only from the complete authoritative candidate catalog. Never add Qwen,
reward, policy, or tensor semantics to Platform contracts. Exact-pin public Platform releases
or explicitly non-stable candidates; never use floating branches or sibling imports.

## Read and work order

Read README, docs/DOCUMENT_MAP.md, docs/STATUS.md, docs/memory/CURRENT.md and docs/memory/DECISIONS.md,
then the owning canonical documents, exact source, and tests. Read
[Development Workflow](docs/DEVELOPMENT_WORKFLOW.md) and
[Engineering Governance](docs/ENGINEERING_GOVERNANCE.md) before editing.

Resolve current remote develop, PR topology, rules and exact base; fetch/prune when the
execution environment supports Git networking. Use one short-lived branch/worktree per writer.
Do not direct-push main/develop, force-update history, or overwrite concurrent work. A connector
read is not a local checkout. Persist meaningful work to a topic branch early.

Identify the owning fact, design the smallest clean causal change, test the failure model,
review the actual diff, repair findings, then update canonical docs and evidence. Failed gates
are work to repair, not permission to weaken them. Worker statements are not evidence.
Merge requires explicit authorization, latest-head checks and all current repository rules.

## One supported bootstrap and gate

Python >=3.11,<3.12 is the machine contract in pyproject.toml and uv.lock.

```bash
uv sync --locked --all-extras
npm ci
uv run --locked python tools/project.py context
uv run --locked python tools/project.py check
uv run --locked python tools/project.py closeout
```

Dependency provisioning may need network. The portable test workload needs no STS2,
proprietary files, raw Human corpus, Qwen weights, GPU, or production credentials.
Linux and Windows execute the same root gate. See [Testing](docs/TESTING.md).

## Code and identity

Use typed public boundaries, frozen durable identities, explicit codecs, and small Protocols.
Keep research/data/model/training independent of storage vendors, SQLite, web UI, and GPU
providers. Source, lock, data, Qwen/tokenizer, serializer, seed, device and dtype are explicit.
Errors identify stage, expected/observed condition and recovery. No generic utility dumping
ground or module-level mutable experiment state. Follow [Code Style](docs/CODE_STYLE.md).

Preserve the historical H1, combat-v0, serializer-v0/v1 and completed S1 smoke lanes unless a
reviewed, tested migration replaces them. Do not relocate them for aesthetics. New Full-Run
contracts are versioned separately. Synthetic evidence never becomes a qualified Human corpus.

## Documentation and safety

Canonical docs own durable statements; memory is routing, not authority. CURRENT is at most
3 KiB. Append accepted decisions and link ADRs from DOCUMENT_MAP. Historical evidence remains
immutable and scoped to its exact source/artifact/runtime/data/model/protocol tuple.

Never commit secrets, raw Human data, private paths/identifiers, proprietary game files, saves,
weights, hidden-state caches, or large generated artifacts. Commit schemas, manifests,
checksums, reproducible commands and reviewed summaries. Keep engineering, data, training,
evaluation, service and scientific evidence independent. No merge transfers evidence.
