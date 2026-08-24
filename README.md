# STS2: The Perfect Defect

> **Status: pre-alpha research project.** The code currently in this repository is a
> real Headless/Connector integration and learning smoke, not the final STPD v0 model.
> It is intentionally retained as a reusable qualification baseline rather than treated
> as disposable prototype code.

STPD studies decision models for *Slay the Spire 2*. The project owns research-state
projection, datasets, model representations, learning, evaluation, and experiment
provenance. It does **not** own game rules, legality, RNG, effects, or execution.

```text
shipped STS2 / qualified Platform Host Runtime
                  |
       Platform Connector component
                  |
       Player Environment contract
                  |
                 STPD
   data -> representation -> model -> training -> evaluation
```

## What exists today

The current package contains the v0 engineering lane, an admitted real frozen-Qwen L2
backend, and the retained H1 integration regression tools:

- `linear_q.py`: a deliberately small linear-Q baseline;
- `training_smoke.py`: real single-environment learning smoke;
- `contention_smoke.py`: multiple isolated actors with one shared learner;
- `multi_seed_learning.py`: repeated learner-seed qualification;
- `reference_transfer.py`: frozen-policy execution on Managed and shipped Reference Hosts;
- `game_seed.py`: deterministic game-valid experiment seeds.

These modules prove that an independent learner can consume the Player Environment and
are expected to remain useful as regression and qualification tools. They do not claim
that linear Q-learning is the final STPD architecture or that the current reward is the
project objective.

The v0 pre-Qwen system is implemented: strict `ResearchState`,
`ResearchAction`, `ResearchTransition`, execution-envelope separation, eligibility,
Lite/Standard/Full deterministic serializers, semantic hashes, schemas, leakage/B0,
canonical Parquet/manifests/splits, a fail-closed AgenticSTS importer, a real Managed
collector, Scheme 1/S2-Simple/S2-SDT, optimizer/checkpoint/evaluation mechanics, B1-B7
report tooling, a pinned metadata/tokenizer Qwen L1 gate, and an exact full-weight
CUDA/BF16 Qwen L2 adapter with a same-architecture frozen random control. FakeQwen remains
the cheap CI backend. Real-Qwen forward/profile/backward smokes are engineering evidence.

The bounded owner-run L2 tiny-overfit sequence is complete. Attempts 001 and 002 remain
retained failures at 64 and 256 steps. Attempt 003 passed the unchanged engineering
criteria at 512 steps: final mean listwise NLL `0.0850893874`, relative reduction
`95.243%`, memorized Top-1 `1.0`, finite values, and zero Qwen gradients. This admits the
optimizer/memorization plumbing only; it is not Gate 1 or model-quality evidence.

The exact AgenticSTS trajectory release was also audited as a potential bootstrap source.
It contains 198,600 decision events and 139,211 combat decisions, but no explicit complete
legal-action catalogs, game seeds, or exact environment identities. Zero records are
rank-eligible under the existing fail-closed contract, so it remains excluded from S1.

A separate fail-closed Human Annotator importer accepts only exact native-UI
records with a complete frozen BoundAction catalog, exact-unique process-local
mapping, stable successor, exact game/Connector/Annotator/Modset identity, and
whole-run roots. It reuses the existing `ResearchProjectorV0`, canonical split,
Parquet, and B0 path. The reusable multi-worker lane adds exact collection
profiles, immutable checksummed session bundles, a pseudonymous filesystem
registry, strict multi-session admission, deterministic whole-run corpus
snapshots, corpus B0/token profiling, and a frozen smoke handoff. Exact native
human sessions now form a 1,962-record cross-platform unified population. The
versioned v2 combination globally reruns collision/deduplication, root-safe split,
B0 and Standard profiling. Serializer v1 removes only redundant combat referent
payload from Standard state text; it does not truncate or alter records. The
result passes B0 and the unchanged Standard P95/hard gates. A formal owner-gated
`S1-1K-2K-SMOKE` runner consumes only its immutable Parquet handoff; Human Gold
and scientific Core remain unavailable.

The owner-run S1 smoke subsequently completed all 1,659 optimizer steps and its
behavior engineering criteria. Its exact final Scheme1 linear checkpoint now has
a separate fail-closed experimental live lane: the official Connector SDK keeps
legality and controller authority, while STPD projects and scores only a whole
complete Defect A0 `play_card`/`end_turn` catalog. Human remains the default for
all other game decisions. See
[Experimental Live S1 Operations](docs/LIVE_S1_OPERATIONS.md).

## What v0 will build

STPD v0 is a combat-focused representation and architecture study. It freezes
`Qwen/Qwen3-0.6B-Base` for the core experiments and compares:

1. **Scheme 1 — Direct Joint Scoring**: `(state, action) -> score`;
2. **S2-Simple**: single-vector latent transition and value;
3. **S2-SDT**: learned world tokens plus an action-conditioned State Dynamics Transformer.

The first architecture phase contains 10 configurations and 3 training seeds per
configuration. Evaluation is organized into B0-B7: contract/leakage, behavior holdout,
human gold, state-action coupling, successor dynamics, current-patch transfer, fixed-seed
live combat, and compute/scaling. Gates 0-5 are the actual sequential research decisions;
B0-B7 are supporting evidence families.

See [v0 execution plan](docs/V0_EXECUTION_PLAN.md).

## Project boundaries

- **STS2 / Host** owns the real game transition and stable successor.
- **STS2-AI-PLATFORM / Connector** owns fair-player
  Snapshot/Read/BoundAction/Receipt semantics.
- **STPD** owns research projections, labels, rewards, models, training, and evaluation.
- Host-specific IDs and native operands never become model features.
- Qwen is accessed through a pinned, typed backend interface; model modules do not call
  Hugging Face implementation details directly.

## Quick start: current integration smoke

```bash
uv sync --locked --all-extras
npm ci
uv run pytest
uv run mypy stpd tools
uv run ruff check stpd tests
uv run python tools/doctor.py
```

A real environment run additionally requires one externally prepared exact Managed
candidate. Host Runtime code and both strategy-free clients come from the pinned Platform
package installed by `npm ci`; the candidate remains a separately audited local artifact:

```bash
export STS2_MANAGED_CANDIDATE=/absolute/path/to/<exact-candidate>

PYTHONPATH=node_modules/@rsgcsg/sts2-host-runtime/consumers/python \
  uv run python -m sts2_headless.smoke \
  --candidate "$STS2_MANAGED_CANDIDATE" \
  --max-actions 64 \
  --evidence-file .local/evidence/environment-smoke/report.json

uv run python -m stpd.training_smoke \
  --candidate "$STS2_MANAGED_CANDIDATE"
```

Raw evidence is local and must not be committed.

The original operational environment patch baseline remains predecessor Headless `v1.0.1`, Managed
Host `8dc622b0.../7228541c...`, Connector `v1.1.0-rc.1`
`e065102.../c1877f1a.../64765ea1...`, and Player Environment protocol/SDK
`1.0.0/1.0.0`. Windows x64 has separate candidate identities and evidence; it does not
inherit the macOS operational freeze. A changed identity is a requalification event.
Current tooling installs Connector SDK `1.1.0-rc.1` and Host Runtime
`1.1.0-rc.3` from immutable `STS2-AI-PLATFORM` GitHub Releases. Package identity,
candidate artifact identity, and exact loaded Host identity remain independent evidence.

## Repository navigation

- [Document map](docs/DOCUMENT_MAP.md)
- [Current status](docs/STATUS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Interfaces](docs/INTERFACES.md)
- [Data and provenance](docs/DATA_AND_PROVENANCE.md)
- [Human corpus lane](docs/HUMAN_CORPUS.md)
- [Qwen integration](docs/QWEN_INTEGRATION.md)
- [Qwen L2 operations and owner handoff](docs/QWEN_L2_OPERATIONS.md)
- [Experimental Live S1 operations](docs/LIVE_S1_OPERATIONS.md)
- [Scientific experiment protocol](docs/SCIENTIFIC_EXPERIMENT_PROTOCOL.md)
- [Project system](docs/PROJECT_SYSTEM.md)
- [Roadmap](docs/ROADMAP.md)
- [Pre-Qwen operations and historical L1 handoff](docs/PRE_QWEN_OPERATIONS.md)
- [Agent and contributor rules](AGENTS.md)

The project is evidence-first: a test, implementation, benchmark, and runtime claim are
separate facts. Every result must identify source, data, model, Host, Connector, seeds,
and non-claims.
