# Current Status

## Verdict

**STPD is pre-alpha. The repository currently contains an H1 integration and learning
qualification scaffold, not the complete STPD v0 model system.**

The existing code is not declared obsolete. It is a reusable low-cost baseline for
validating environment consumption, learning, actor/learner contention, provenance, and
Candidate-to-Reference execution while the full v0 architecture is built.

## Current phase

```text
P0: project system and contract initialization
+
H1 environment/consumer qualification
```

The environment lane is aligned to Headless `v1.0.0`, Managed patch
`ed9248b...` / Host `a884b104.../5b6adbd6...`, Connector
`v1.1.0-rc.1/e065102...` / Host `c1877f1a.../64765ea1...`, STS2
`v0.111.0/41cef1ea`, and Player Environment protocol/SDK `1.0.0/1.0.0`.
This is an operational baseline, not formal H1.0 qualification.

The predecessor code baseline was `1b4039fe3933b408e31dd92e9fbe1454bdd7672e`.
The locked Python 3.11 baseline and first v0 contract slice are implemented; runtime claims
remain bound to the exact reports that produced them.

## Implemented

- independent Python consumer of the Headless Player Environment;
- finite action-set checks and fail-closed delivery handling;
- small linear-Q learner and shaped-reward integration smoke;
- multi-seed learning harness;
- multi-environment actor/shared-learner contention harness;
- model freeze/load path for the smoke learner;
- Managed-to-shipped-Reference execution harness;
- seed derivation, exact Host provenance, temporal settling/stale supervision;
- locale-neutral action ordering for the qualification policy while retaining
  localized labels in evidence;
- a cheap fail-closed environment smoke before training;
- pure unit tests for the current smoke lane;
- project document map, memory/ADR workflow, and typed ports;
- strict ResearchState, ResearchAction, ResearchTransition, policy/environment identity,
  eligibility, and execution-envelope contracts;
- deterministic Lite/Standard/Full ModelState and ModelAction serialization, semantic
  hashes, model-input leakage rejection, strict schemas, and a golden transition fixture.
- raw JSONL ingestion, canonical Parquet round-trip, checksummed data manifests,
  deterministic seed-root splits, and an executable fail-closed B0 gate.
- trainable PyTorch Scheme 1, S2-Simple, and S2-SDT forward paths with candidate-set
  ranking, successor/anchor losses, learned world tokens, and EMA target resampling.

## Not yet implemented

- frozen Qwen backend and random frozen control;
- production-source dataset collection/import and large-corpus near-deduplication;
- candidate-set ranking training stack;
- B0-B7 benchmark implementation and Human Gold workflow;
- experiment registry, model artifact registry, and final report generator;
- v0 core 30-run matrix or input-ablation runs;
- offline/online RL beyond the current integration smoke.

## Current non-claims

- The linear-Q model is not the planned STPD model.
- Its shaped reward is not the final project objective or a calibrated win-probability Q.
- The frozen structural contracts do not prove a real dataset or Headless collector.
- A successful smoke does not prove broad semantic parity, policy quality, or H1 admission.
- No Qwen representation, Scheme 1/Scheme 2 hypothesis, Human Gold result, or v0 benchmark
  has been measured by this repository yet.
- No raw data, Qwen weights, proprietary game files, or private runtime evidence are part of
  the source tree.
- Long soak, exhaustive semantics, broad changed-build/fault and cross-platform
  qualification remain deferred non-claims rather than STPD v0 blockers.

## Immediate priorities

1. Build the Headless collector and AgenticSTS importer against the frozen contracts.
2. Exercise the data/B0 pipeline on source-representative local samples.
3. Implement a pinned frozen-Qwen backend with pretrained and random controls.
4. Add optimizer/checkpoint/resume and independent evaluation around the implemented models.
5. Keep the current smoke lane green as an environment regression gate.

See [Roadmap](ROADMAP.md) and [v0 Execution Plan](V0_EXECUTION_PLAN.md).
