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

## v0 Step 1 — Token and compute profiling

Status: **L2 engineering admission complete; admitted-corpus profiling partial**. The
immutable config/tokenizer/full-weight snapshot and all three serializers are implemented.
Pretrained and seeded same-architecture random frozen backends pass deterministic
CUDA/BF16 representation and all-family backward-only smokes. A synthetic 1,024-token
pretrained measurement took 0.145 seconds with about 1.30 GB process peak allocated VRAM
on the recorded RTX 4070 Laptop GPU. Current natural `turn_action` samples pass the token
gate; `card_selection` and `card_choice` remain `not_exercised`.

Measure Lite/Standard/Full token distributions, legal-action counts, frozen-Qwen latency,
VRAM, cold compute, cached compute, and storage costs.

## v0 Step 1.5 — Owner optimizer-plumbing admission

Status: **attempt-001 completed; protocol-r1 retry pending owner execution**.

The original 64-step Scheme 1 linear tiny-overfit reached 100% memorized Top-1 but ended at
mean NLL `0.9022365957` and relative loss reduction `49.56%`, so it correctly failed the
unchanged NLL <= 0.1 and reduction >= 90% thresholds. Its loss was still decreasing through
step 64. The failed attempt remains retained.

Protocol `stpd-v0-l2-2026-08-22-r1` changes only this bounded engineering retry budget to
256 optimizer steps and emits `attempt-002`. Data selection, Qwen, architecture, seed,
AdamW/lr, pass criteria, Core matrix and scientific Gates remain unchanged.

This step is a plumbing/memorization admission check. Passing it is not Gate 1 and does not
establish pretrained representation value.

## v0 Steps 2-4 — Core architecture selection

Status: **protocol r1 frozen; scientific Core training not started**. The exact 10
configurations and three seeds are machine-readable. The bounded r1 tiny-overfit retry must
be resolved before the first scientific Core run.

Before Core training, scientific data admission, Gold-dev, sealed Gold-test identity,
required controls, selector-family coverage status and exact split/manifests must be ready.

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
