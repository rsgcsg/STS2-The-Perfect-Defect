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

The predecessor code baseline was `1b4039fe3933b408e31dd92e9fbe1454bdd7672e`.
This project-system initialization establishes the canonical documents and future module
boundaries; runtime claims remain bound to the exact reports that produced them.

## Implemented

- independent Python consumer of the Headless Player Environment;
- finite action-set checks and fail-closed delivery handling;
- small linear-Q learner and shaped-reward integration smoke;
- multi-seed learning harness;
- multi-environment actor/shared-learner contention harness;
- model freeze/load path for the smoke learner;
- Managed-to-shipped-Reference execution harness;
- seed derivation, exact Host provenance, temporal settling/stale supervision;
- pure unit tests for the current smoke lane.

## Not yet implemented

- frozen Qwen backend and random frozen control;
- canonical ResearchState, ModelState Lite/Standard/Full, and ModelAction v0;
- dataset ingestion, eligibility, split, deduplication, and manifest pipeline;
- Scheme 1 Direct Joint Scoring;
- S2-Simple and S2-SDT;
- candidate-set ranking training stack;
- B0-B7 benchmark implementation and Human Gold workflow;
- experiment registry, model artifact registry, and final report generator;
- v0 core 30-run matrix or input-ablation runs;
- offline/online RL beyond the current integration smoke.

## Current non-claims

- The linear-Q model is not the planned STPD model.
- Its shaped reward is not the final project objective or a calibrated win-probability Q.
- A successful smoke does not prove broad semantic parity, policy quality, or H1 admission.
- No Qwen representation, Scheme 1/Scheme 2 hypothesis, Human Gold result, or v0 benchmark
  has been measured by this repository yet.
- No raw data, Qwen weights, proprietary game files, or private runtime evidence are part of
  the source tree.

## Immediate priorities

1. Freeze ResearchState/ModelState/ModelAction/ResearchTransition v0 contracts.
2. Establish B0 dataset-contract and leakage checks.
3. Implement a pinned frozen-Qwen backend with pretrained and random controls.
4. Build the smallest Scheme 1 baseline before adding Scheme 2.
5. Keep the current smoke lane green as an environment regression gate.

See [Roadmap](ROADMAP.md) and [v0 Execution Plan](V0_EXECUTION_PLAN.md).
