# Document Map

This map is the entry point for human and agent navigation.

## Source-of-truth order

1. Executable code, tests, and machine-readable schemas.
2. `STATUS.md` for current claims and non-claims.
3. Architecture and interface documents for durable boundaries.
4. The v0 plan and roadmap for intended work.
5. ADRs for accepted long-lived decisions.
6. Memory files for short-lived working context.
7. External notes and conversations as research input only.

When two levels disagree, stop and resolve the drift; do not silently pick the preferred
answer.

## Canonical documents

| Document | Purpose | Update when |
|---|---|---|
| [Status](STATUS.md) | current implemented/measured/planned state | a fact or claim changes |
| [Architecture](ARCHITECTURE.md) | ownership, layers, dependency direction | a boundary changes |
| [Interfaces](INTERFACES.md) | environment, data, model, artifact formats | a public contract changes |
| [Data and Provenance](DATA_AND_PROVENANCE.md) | data zones, eligibility, splits, external data | data policy changes |
| [Human Corpus Lane](HUMAN_CORPUS.md) | collection profiles, bundles, registry, corpus and smoke handoff | human corpus semantics or operations change |
| [Qwen Integration](QWEN_INTEGRATION.md) | frozen-backbone adapter and cache contract | Qwen use changes |
| [Qwen L2 Operations](QWEN_L2_OPERATIONS.md) | exact full-weight admission, engineering smokes, data preparation and owner stop | L2 operational identity changes |
| [Experimental Live S1 Operations](LIVE_S1_OPERATIONS.md) | exact checkpoint-to-Connector handoff, controls and fail-closed live evidence | live policy execution changes |
| [B0-B7 Benchmarks](BENCHMARKS.md) | executable gates, reports, and evidence boundaries | benchmark mechanics change |
| [Scientific Experiment Protocol](SCIENTIFIC_EXPERIMENT_PROTOCOL.md) | frozen 10-config matrix, controls, Gates 0-5, Gold and owner-training boundaries | scientific protocol changes |
| [v0 Execution Plan](V0_EXECUTION_PLAN.md) | v0 experiments, benchmarks, gates, deliverables | v0 scope changes |
| [Roadmap](ROADMAP.md) | phase sequencing and definitions of done | priority/phase changes |
| [Project System](PROJECT_SYSTEM.md) | docs, memory, experiment and decision workflow | project workflow changes |
| [Code Style](CODE_STYLE.md) | code and formatting conventions | style/test rules change |
| [Pre-Qwen Operations](PRE_QWEN_OPERATIONS.md) | doctor, artifacts, historical L1 handoff | L1 operational identity changes |

## Current evidence

- [AgenticSTS data-admission audit](evidence/AGENTICSTS_DATA_ADMISSION_AUDIT_2026-08-22.md)

The Human Annotator raw contract is owned by the Annotator component in
`STS2-AI-PLATFORM`. STPD's strict importer is
`stpd/data/human_annotator.py`; this map does not duplicate that external schema.

## Working memory

- [Memory instructions](memory/README.md)
- [Current context](memory/CURRENT.md)
- [Accepted decisions](memory/DECISIONS.md)
- [Open questions](memory/OPEN_QUESTIONS.md)
- [Latest handoff](memory/HANDOFF.md)

Memory is deliberately simple Markdown. It helps continuity but cannot override code,
schemas, status, or ADRs.

## Decisions

- [ADR index](adr/README.md)
- [ADR-0001: project boundaries and current smoke](adr/0001-project-boundaries-and-current-smoke.md)
- [ADR-0002: versioned unified Human serialization](adr/0002-versioned-unified-human-serialization.md)

## Machine-readable contracts

See [`../schemas/README.md`](../schemas/README.md).

## External project roots

- `STS2-AI-PLATFORM`: Host lifecycle, exact identity, Human Annotator, and the
  Host-neutral Player Environment contract/SDK/authority.
- `STS2-The-Perfect-Defect`: research projection, data, Qwen/model, training, evaluation.

External repositories are dependencies, not submodules or copied sources.
