# STS2: The Perfect Defect

> **Status: pre-alpha research project.** The code currently in this repository is a
> real Headless/Connector integration and learning smoke, not the final STPD v0 model.
> It is intentionally retained as a reusable qualification baseline rather than treated
> as disposable prototype code.

STPD studies decision models for *Slay the Spire 2*. The project owns research-state
projection, datasets, model representations, learning, evaluation, and experiment
provenance. It does **not** own game rules, legality, RNG, effects, or execution.

```text
shipped STS2 / qualified Headless Host
                  |
          STS2-Connector
                  |
       Player Environment contract
                  |
                 STPD
   data -> representation -> model -> training -> evaluation
```

## What exists today

The current package contains the complete pre-Qwen v0 engineering lane plus the retained
H1 integration regression tools:

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
report tooling, and a pinned metadata/tokenizer-only Qwen L1 gate. FakeQwen drives the
whole engineering path but is not scientific Qwen evidence.

## What v0 will build

STPD v0 is a combat-focused representation and architecture study. It freezes
`Qwen/Qwen3-0.6B-Base` for the core experiments and compares:

1. **Scheme 1 — Direct Joint Scoring**: `(state, action) -> score`;
2. **S2-Simple**: single-vector latent transition and value;
3. **S2-SDT**: learned world tokens plus an action-conditioned State Dynamics Transformer.

The first architecture phase contains 10 configurations and 3 training seeds per
configuration. Evaluation is organized into B0-B7: contract/leakage, behavior holdout,
human gold, state-action coupling, successor dynamics, current-patch transfer, fixed-seed
live combat, and compute/scaling.

See [v0 execution plan](docs/V0_EXECUTION_PLAN.md).

## Project boundaries

- **STS2 / Host** owns the real game transition and stable successor.
- **STS2-Connector** owns fair-player Snapshot/Read/BoundAction/Receipt semantics.
- **STPD** owns research projections, labels, rewards, models, training, and evaluation.
- Host-specific IDs and native operands never become model features.
- Qwen is accessed through a pinned, typed backend interface; model modules do not call
  Hugging Face implementation details directly.

## Quick start: current integration smoke

```bash
uv sync --locked --all-extras
uv run pytest
uv run mypy stpd tools
uv run ruff check stpd tests
uv run python tools/doctor.py
```

A real environment run additionally requires a prepared `STS2-headless` candidate:

```bash
PYTHONPATH=../STS2-headless/consumers/python \
  python3 -m sts2_headless.smoke \
  --candidate ../STS2-headless/.local/candidates/<exact-candidate> \
  --max-actions 64 \
  --evidence-file .local/evidence/environment-smoke/report.json

python3 -m stpd.training_smoke \
  --headless ../STS2-headless \
  --candidate ../STS2-headless/.local/candidates/<exact-candidate>
```

Raw evidence is local and must not be committed.

The current environment patch baseline is Headless `v1.0.1`, Managed Host
`8dc622b0.../7228541c...`, Connector `v1.1.0-rc.1`
`e065102.../c1877f1a.../64765ea1...`, and Player Environment protocol/SDK
`1.0.0/1.0.0`. A changed identity is a requalification event.

## Repository navigation

- [Document map](docs/DOCUMENT_MAP.md)
- [Current status](docs/STATUS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Interfaces](docs/INTERFACES.md)
- [Data and provenance](docs/DATA_AND_PROVENANCE.md)
- [Qwen integration](docs/QWEN_INTEGRATION.md)
- [Project system](docs/PROJECT_SYSTEM.md)
- [Roadmap](docs/ROADMAP.md)
- [Pre-Qwen operations and L2 handoff](docs/PRE_QWEN_OPERATIONS.md)
- [Agent and contributor rules](AGENTS.md)

The project is evidence-first: a test, implementation, benchmark, and runtime claim are
separate facts. Every result must identify source, data, model, Host, Connector, seeds,
and non-claims.
