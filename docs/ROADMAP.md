# Roadmap

## P0 — Project and contract foundation

Status: **implemented and automated**.

Definition of done:

- canonical documents, memory, ADR, schemas, and repository boundaries exist;
- current smoke lane remains runnable and explicitly classified;
- ResearchState, ModelState, ModelAction, ResearchTransition, experiment, and artifact
  contracts are reviewed and machine-readable;
- external data policy and B0 checks are defined;
- Headless/Connector/Qwen boundaries are testable.

## v0 Step 0 — Data and contract freeze

Status: **implemented** for the v0 contract and current bounded collector. Large-corpus
near-duplicate analysis and scientific data admission remain dataset-scale work.

Deliver:

- ResearchState and ModelState Lite/Standard/Full;
- ModelAction v0;
- stable-successor transition construction;
- provenance and eligibility flags;
- episode/run/seed-root split manifests;
- B0 contract, leakage, deduplication, and split checks.

No model result is interpretable until this step passes.

The multi-worker Human Corpus infrastructure is implemented: versioned exact
profiles/campaigns, immutable session bundles, fail-closed registry admission,
deterministic multi-source corpus snapshots, whole-run plus semantic-duplicate
component splitting, corpus B0, Standard profiling and frozen smoke handoff.
Automated tests cover drift, tampering, collisions, retries, input reordering and
snapshot immutability. Four real bundles now provide 1,962 admitted decisions.

The final cross-profile layer is implemented. It accepts only immutable
admitted profile snapshots, checks a versioned compatibility plan, preserves
source/platform/session provenance and globally reruns collision/dedup,
whole-run splitting, B0 and Standard profiling. The v2 unified population has
775 macOS and 1,187 Windows records.

Serializer v1 resolves only redundant Standard combat rendering while retaining
the evidence contract. The unified corpus passes B0 and unchanged token gates at
P95 2,883 and max 4,110 without truncation or threshold relaxation.

The next Human evidence contract is implemented at source/test level: STPD now
consumes Platform-verified V2 bundles, materializes `run_deck` and
`combat_piles` through the existing research projection, and keeps V1 behavior
under parity tests. Exact native-human V2 capture, transfer and corpus admission
remain pending runtime evidence and do not reopen the frozen V1 smoke corpus.

## v0 Step 1 — Token and compute profiling

Status: **L2 engineering admission complete; admitted-corpus profiling partial**. The
immutable config/tokenizer/full-weight snapshot and all three serializers are implemented.
Pretrained and seeded same-architecture random frozen backends pass deterministic
CUDA/BF16 representation and all-family backward-only smokes. A synthetic 1,024-token
pretrained measurement took 0.145 seconds with about 1.30 GB process peak allocated VRAM
on the recorded RTX 4070 Laptop GPU. Current natural `turn_action` samples pass the token
gate; `card_selection` and `card_choice` remain `not_exercised`.

## v0 Step 1.5 — Owner optimizer-plumbing admission

Status: **completed as engineering admission**.

Attempt-001 used 64 optimizer steps and ended at mean NLL `0.9022365957`, relative loss
reduction `49.56%`, and 100% memorized Top-1. Attempt-002 used 256 steps and ended at mean
NLL `0.2385502681`, relative loss reduction `86.66%`, and 100% memorized Top-1. Both kept
finite values and zero Qwen gradients; both correctly failed the unchanged NLL <= 0.1 and
reduction >= 90% thresholds.

Attempt-002 remained smoothly decreasing through steps 64/128/192/256:
`0.9022 / 0.5347 / 0.3453 / 0.2386`, with no observed plateau.

Protocol `stpd-v0-l2-2026-08-22-r2` made one final budget-only retry at 512 optimizer
steps. Attempt-003 passed with final mean listwise NLL `0.08508938737213612`, relative
reduction `0.9524300409255195`, memorized Top-1 `1.0`, finite values, and zero Qwen
gradients. Data selection, Qwen, architecture, seed, AdamW/lr, pass criteria, Core matrix,
and scientific Gates remained unchanged. Attempts 001 and 002 remain retained failures.

This step is a plumbing/memorization admission check. Passing it is not Gate 1 and does not
establish pretrained representation value.

## v0 Steps 2-4 — Core architecture selection

Status: **protocol r2 frozen; S1 owner handoff ready; scientific Core not ready**.
The exact 10 configurations and three seeds are machine-readable. Tiny-overfit engineering
admission is complete, but the audited AgenticSTS source supplies 0 rank-eligible rows from
198,600 decisions because complete legal catalogs, game seeds, and exact environment
identities are absent.

Before Core training, Human Gold-dev, sealed Gold-test identity,
required controls, selector-family coverage status and exact split/manifests must be ready.
The behavior S1 corpus has passed its 1,500-record, B0, split/leakage and Standard
token gates. Its owner-gated smoke remains distinct from scientific Core.

Run Standard input for:

- 4 Scheme 1 configurations;
- 4 S2-Simple configurations;
- 2 S2-SDT configurations;
- 3 random seeds each, 30 core runs total.

Evaluate B1-B5 and B7, then freeze the best pretrained Scheme 1 and Scheme 2 candidates.

## v0 Step 5 — Input ablation

Run Lite and Full only for the two frozen winners. Together with Standard, the planned v0
matrix is about 42 runs before debugging/retries.

## v0 Step 6 — Final held-out evaluation

After architecture, input, and hyperparameters are frozen:

- open Gold-test once;
- run the paired fixed-seed live combat suite;
- report bootstrap confidence intervals and quality/compute Pareto results.

## v0 Step 7 — Decide the next research phase

Possible outcomes include Scheme 1, S2-Simple, or S2-SDT continuation; a tie defaults to
the simpler model. Random approximately equal to pretrained pauses Qwen expansion and
reopens data/serialization/target assumptions.

## Post-v0

- return probe and behavior-value analysis;
- conservative offline RL baselines such as CQL/IQL;
- real-successor TD learning;
- online RL only after Host/Connector training qualification;
- checkpoint/branch counterfactual work only after a separately qualified Host capability.

## Explicitly deferred

- LoRA or full Qwen fine-tuning before the frozen-representation gate;
- large model scaling as a substitute for weak data/contracts;
- imagined multi-step rollout before one-step dynamics are qualified;
- reward/model semantics in Headless or Connector;
- a second gameplay legality or rules engine in STPD.
