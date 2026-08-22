# Current Context

## Phase

Windows L2 full-weight engineering closeout and bounded owner-training preparation, while
preserving the H1 integration smoke as an environment regression lane.

## Current truths

- The existing linear-Q and transfer code is real and useful, but not the final v0 model.
- STPD owns research/data/model/training/evaluation, not game truth or legality.
- v0 core uses frozen Qwen3-0.6B-Base and Standard input.
- ResearchState/ResearchAction/ResearchTransition and deterministic Lite/Standard/Full
  ModelState/ModelAction structural contracts are frozen and tested.
- Canonical Parquet, data manifests, seed-root split assignment, executable B0, a bounded
  current Managed collector, and the fail-closed AgenticSTS importer are implemented.
- Scheme 1, S2-Simple, and S2-SDT have real PyTorch forward/loss/gradient tests against
  FakeQwen and exact full-weight frozen Qwen. The real pretrained/random smokes are
  engineering evidence; no scientific result has been measured.
- Candidate-set optimizer, identity-bound checkpoint/resume, and independent B1 ranking
  metrics are implemented and synthetic-tested.
- Player Environment projection/collection is implemented and synthetic-tested, including
  Read completeness, exact receipt, stable successor, unknown-no-retry, and runtime drift.
- B0-B7 evaluation/report mechanics are implemented with synthetic counterexamples; there
  are no B1-B7 scientific result claims yet.
- Scheme 1, S2-Simple and S2-SDT run optimizer/checkpoint/evaluation paths through
  DeterministicFakeQwenBackend; this is engineering evidence only.
- Exact Qwen revision `da87bfb...` is pinned and present outside Git; pretrained and seeded
  same-architecture random frozen backends pass CUDA/BF16 determinism, cache, VRAM/latency,
  all-family backward-only, and zero-Qwen-gradient checks.
- The exact 10-config/three-seed protocol, required controls, Gates 0-5, Gold/B6 boundaries,
  and owner-gated 64-step L2 tiny-overfit are frozen before real training.
- The exact operational environment baseline is Headless `v1.0.1`, Managed
  Host `8dc622b0.../7228541c...`, Connector `v1.1.0-rc.1/e065102...`
  `c1877f1a.../64765ea1...`, protocol/SDK `1.0.0/1.0.0`.
- This baseline is STPD-ready but not formal H1.0; long qualification campaigns
  are deferred until a concrete environment regression reopens them.

## Immediate priorities

1. Commit the exact source, collect a bounded complete-catalog Managed ranking fixture, and
   replay B0 under the clean source identity.
2. Prepare and persist the exact L2 tiny-overfit owner manifest, then stop before training.
3. Collect natural selector-family token samples before interpreting the aggregate gate.
4. Keep environment, FakeQwen, and real-Qwen engineering smokes green.

## Do not do yet

- move the smoke modules for cosmetic reasons;
- fine-tune Qwen before the frozen pretraining-value gate;
- run `l2_tiny_overfit.py run` without exact owner authorization;
- open Gold test or execute B6 before architecture/input/hyperparameter freeze;
- put reward/model/tensor semantics in Headless or Connector;
- scale data/model complexity before B0 and contract freeze.
