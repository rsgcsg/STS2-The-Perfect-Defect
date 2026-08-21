# STPD v0 Execution Plan

This is the canonical condensed implementation plan derived from the dated
`STPD_V0_TRAINING_BENCHMARK_AND_RL_PLAN_2026-08-22` research specification.

## Goal and scope

v0 asks whether frozen Qwen representations support useful combat action ranking and whether
an explicit action-conditioned latent successor structure improves real decisions. It is not
an immediate claim of optimal Q, full-run mastery, or production online RL.

Scope:

- combat stable interactive decisions;
- complete finite legal action set from Connector;
- default input `stpd-combat-v0-standard`;
- frozen `Qwen/Qwen3-0.6B-Base`;
- output `Q_theta(s, a)` interpreted initially as an action-ranking score.

## Core architectures

### Scheme 1 — Direct Joint Scoring

`FrozenQwen(state, action) -> pooled representation -> Linear or MLP head`.

Four configurations: random/pretrained frozen backbone × linear/MLP head.

### S2-Simple

`Frozen state vector + frozen action vector -> residual transition G -> value V`.

Four configurations: random/pretrained × successor supervision off/on.

### S2-SDT

`Frozen state hidden sequence -> 32x512 learned world tokens`; action token embeddings enter
a two-layer 512-dimension State Dynamics Transformer; value reads the predicted world state.

Two core configurations: pretrained backbone, successor supervision off/on. A small anchor
head is training-only; the successor target uses an EMA Resampler.

## Core run matrix

```text
Scheme 1      4 configs
S2-Simple     4 configs
S2-SDT        2 configs
              ---------
              10 configs x 3 seeds = 30 core runs
```

All core runs use Standard input. After selecting the best pretrained Scheme 1 and Scheme 2,
run Lite and Full for each winner: four additional configs × three seeds. Planned total after
input ablation is about 42 runs, excluding debugging and failed runs.

## Supervision

- ranking loss uses rank-eligible behavior choices grouped by current candidate set;
- successor loss uses transition-eligible real stable successors;
- return probes use return-eligible complete trajectories;
- teacher choice is behavior supervision, not optimal-Q truth;
- random actions may train dynamics but are not default positive ranking labels.

Core Scheme 1 uses ranking only. S2-Simple and S2-SDT each have successor OFF/ON variants.
Trajectory outcome is a later probe, not mixed into first-round architecture selection.

## Benchmark families

- **B0** contract, leakage, dataset integrity — hard gate;
- **B1** behavior holdout and state-blind action-prior baseline;
- **B2** Human Gold dev/test with acceptable actions and disagreement estimate;
- **B3** state-action coupling and controlled counterfactual diagnostics;
- **B4** successor/dynamics, including action-successor retrieval;
- **B5** current-patch and environment transfer by provenance;
- **B6** paired fixed-seed live combat suite;
- **B7** token, VRAM, GPU-hour, latency, action-count, and cache scaling.

Interpretation priority: B6 > B2 approximately B3 > B5 > B1 > training loss. B4 explains
whether dynamics work but cannot alone select the final decision architecture.

## Execution stages

1. **Contract freeze**: ResearchState/ModelState/ModelAction/Transition, manifests, B0.
2. **Token/compute profiling**: input lengths, action counts, latency, VRAM, caches.
3. **Core training**: 30 Standard-input runs.
4. **Core benchmark**: B1-B5 and B7, Gold-dev only.
5. **Candidate freeze**: best pretrained Scheme 1 and Scheme 2.
6. **Input ablation**: Lite and Full for the two winners.
7. **Final evaluation**: one-time Gold-test and paired B6.
8. **Decision**: select next-phase architecture or reject unsupported assumptions.

## Architecture gates

- **A Pretraining value**: pretrained must beat random on held-out decision evidence.
- **B Scheme 1 viability**: beat random legal, state-blind action prior, and useful heuristics.
- **C Simple successor hypothesis**: successor loss must improve decision evidence, not only
  latent metrics.
- **D Structured dynamics value**: SDT must justify multi-token dynamics over Simple.
- **E Final Scheme 1 vs Scheme 2**: same data, inputs, Gold, live suite, and reporting; ties
  select the simpler/faster model.

## Statistical and compute reporting

- three seeds per core configuration;
- paired evaluation and bootstrap 95% confidence intervals;
- practical significance and Pareto analysis, not one arbitrary total score;
- data scaling, GPU-hour scaling, input/token curve, legal-action-count scaling;
- cold and cached compute reported separately.

## v0 definition of done

v0 is complete when the repository can reproducibly answer:

1. whether pretrained Qwen is better than random control;
2. whether direct joint scoring is viable;
3. whether successor supervision improves decisions;
4. whether SDT beats the single-vector baseline enough to justify cost;
5. which input profile has the best quality/compute Pareto;
6. how behavior imitation transfers to Human Gold/current patch/live combat;
7. which architecture, if any, should enter offline RL.

A beautiful latent loss without Gold/live decision improvement is not success.
