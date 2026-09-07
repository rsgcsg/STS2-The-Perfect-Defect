# Document Map

Routing only: exact source/contracts/tests and scoped artifact/runtime evidence establish
facts. Canonical documents describe supported claims; ADRs/plans define accepted intent;
working memory and historical conversations do not prove implementation. Separate evidence
classes are defined in [Engineering Governance](ENGINEERING_GOVERNANCE.md).

## Entry and engineering

| Document | Responsibility |
|---|---|
| [New Engineer Guide](NEW_ENGINEER_GUIDE.md) | first checkout and ownership orientation |
| [Status](STATUS.md) | implemented/measured state and non-claims |
| [Project System](PROJECT_SYSTEM.md) | context/check/closeout and bounded memory |
| [Development Workflow](DEVELOPMENT_WORKFLOW.md) | branches, PRs, releases and exact dependencies |
| [Engineering Governance](ENGINEERING_GOVERNANCE.md) | ownership, failure models, review and evidence |
| [Testing](TESTING.md) | complete portable gate and external qualification boundaries |
| [Code Style](CODE_STYLE.md) | language, typed interfaces and determinism |
| [Architecture](ARCHITECTURE.md) | research/environment dependency direction |
| [Interfaces](INTERFACES.md) | versioned environment, data, model and artifact contracts |

## Research and operations

| Document | Responsibility |
|---|---|
| [Data and Provenance](DATA_AND_PROVENANCE.md) | admission, zones, splits and external data |
| [Data Lifecycle](DATA_LIFECYCLE.md) | canonical storage, derived features and staging |
| [Human Corpus](HUMAN_CORPUS.md) | profiles, verified bundles and corpus admission |
| [Qwen Integration](QWEN_INTEGRATION.md) | pinned backbone and cache contract |
| [Qwen L2 Operations](QWEN_L2_OPERATIONS.md) | exact weight admission and owner gates |
| [Live S1 Operations](LIVE_S1_OPERATIONS.md) | historical S1 policy adapter/parity |
| [Benchmarks](BENCHMARKS.md) | B0-B7 mechanics and evidence scope |
| [Scientific Protocol](SCIENTIFIC_EXPERIMENT_PROTOCOL.md) | historical combat-v0 protocol |
| [v0 Plan](V0_EXECUTION_PLAN.md) | retained combat-v0 study |
| [Roadmap](ROADMAP.md) | priorities and phase definitions |
| [Pre-Qwen Operations](PRE_QWEN_OPERATIONS.md) | historical L1 handoff |

## Evidence, decisions and memory

[AgenticSTS Audit](evidence/AGENTICSTS_DATA_ADMISSION_AUDIT_2026-08-22.md) and
[Data Lifecycle Closeout](evidence/DATA_LIFECYCLE_ENGINEERING_CLOSEOUT_2026-08-29.md)
remain scoped historical records. The Platform Annotator schema is externally owned;
stpd/data/human_annotator.py consumes it without making this map a second schema authority.

[ADR Index](adr/README.md), [ADR-0001](adr/0001-project-boundaries-and-current-smoke.md),
[ADR-0002](adr/0002-versioned-unified-human-serialization.md),
[Memory Instructions](memory/README.md), [Current Context](memory/CURRENT.md),
[Decisions](memory/DECISIONS.md), [Open Questions](memory/OPEN_QUESTIONS.md),
[Latest Handoff](memory/HANDOFF.md), and [Machine Contracts](../schemas/README.md).

Platform owns model-neutral environment/runtime/evidence contracts. STPD owns research,
data, representation, training and evaluation. External repositories are exact dependencies,
not copied source trees, shared branches or submodules.

[Local-First manifest ADR](adr/0003-local-first-manifest-research.md)

[Full-Run Research](FULLRUN_RESEARCH.md)

[Full-Run Training](FULLRUN_TRAINING.md)

## Pre-Full-Run convergence

- [Local operations and exact Worker launch](PREFULLRUN_OPERATIONS.md)
- [Local DuckDB and dashboard](LOCAL_WORKBENCH.md)
- [Gold and E0-E7 engineering tooling](FULLRUN_GOLD.md)
