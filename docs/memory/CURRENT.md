# Current Context

## Phase

P0 project-system and contract initialization, while preserving the H1 integration smoke as
a regression/qualification lane.

## Current truths

- The existing linear-Q and transfer code is real and useful, but not the final v0 model.
- STPD owns research/data/model/training/evaluation, not game truth or legality.
- v0 core uses frozen Qwen3-0.6B-Base and Standard input.
- ResearchState/ResearchAction/ResearchTransition and deterministic Lite/Standard/Full
  ModelState/ModelAction structural contracts are frozen and tested.
- Canonical Parquet, data manifests, seed-root split assignment, and executable B0 are
  implemented and fixture-tested; no production dataset claim has been made.
- Scheme 1, S2-Simple, and S2-SDT have real PyTorch forward/loss/gradient tests against an
  engineering backend; no real Qwen or scientific result has been measured.
- Candidate-set optimizer, identity-bound checkpoint/resume, and independent B1 ranking
  metrics are implemented and synthetic-tested.
- Player Environment projection/collection is implemented and synthetic-tested, including
  Read completeness, exact receipt, stable successor, unknown-no-retry, and runtime drift.
- No Scheme 1, S2-Simple, S2-SDT, Human Gold, or B0-B7 production pipeline exists yet.
- The exact operational environment baseline is Headless `v1.0.0`, Managed
  Host `a884b104.../5b6adbd6...`, Connector `v1.1.0-rc.1/e065102...`
  `c1877f1a.../64765ea1...`, protocol/SDK `1.0.0/1.0.0`.
- This baseline is STPD-ready but not formal H1.0; long qualification campaigns
  are deferred until a concrete environment regression reopens them.

## Immediate priorities

1. Implement the current Headless collector and AgenticSTS importer.
2. Run source-representative samples through canonical Parquet and B0.
3. Implement the pinned frozen-Qwen backend.
4. Implement the smallest pretrained/random Scheme 1 baseline.
5. Keep current smoke tests and real environment qualification usable.

## Do not do yet

- move the smoke modules for cosmetic reasons;
- fine-tune Qwen before the frozen pretraining-value gate;
- put reward/model/tensor semantics in Headless or Connector;
- scale data/model complexity before B0 and contract freeze.
