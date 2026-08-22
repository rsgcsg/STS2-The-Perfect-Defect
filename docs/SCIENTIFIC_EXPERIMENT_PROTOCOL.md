# STPD v0 Scientific Experiment Protocol

Status: frozen before real-dataset multi-step L2 training
Protocol version: `stpd-v0-l2-2026-08-22`

This document is the preregistered decision boundary for v0. It narrows the architecture
plan into executable comparisons; it does not report a scientific result. Any material
change after the first owner training run creates a new protocol version and requires all
affected runs to be repeated.

## Immutable admission identity

Every scientific run must bind all of the following in an experiment manifest:

- clean STPD source SHA and this protocol version;
- canonical data-manifest SHA, Parquet SHA, source/license provenance, split assignment,
  serializer version, and B0 report SHA;
- `Qwen/Qwen3-0.6B-Base` revision
  `da87bfb608c14b7cf20ba1ce41287e8de496c0cd`;
- `model.safetensors` SHA-256
  `cd2a512003e2f9f3cd3c32a9c3573f820bb28c940f73c57b1ddaa983d9223eba`;
- Qwen config, tokenizer-bundle, control, dtype, device, framework, attention,
  serializer, feature dtype, and cache identities;
- random-control seed and full initialization SHA-256 when the control is `random`;
- architecture/config digest, optimizer, budget, seed, checkpoint, evaluation, and
  artifact destinations.

Moving revisions, partial catalogs, silent truncation, mixed runtime provenance, unknown
licenses, missing hashes, or an identity mismatch fail closed. FakeQwen is an engineering
double only and is never admitted as a scientific random control.

## Core matrix and fixed seeds

`configs/v0/models/core.json` is the authoritative 10-configuration matrix. Each identity
runs seeds `20260822`, `20260823`, and `20260824`, for 30 core runs. All use Standard input,
the exact data split manifests, AdamW settings from the bound experiment configuration,
one complete candidate set per ranking batch, and executed-action-only successor targets.

Scheme 1 has pretrained/random Qwen crossed with linear/MLP heads. S2-Simple has
pretrained/random Qwen crossed with successor supervision off/on. S2-SDT uses pretrained
Qwen with successor supervision off/on. Random-Qwen SDT is outside the core matrix because
Gate 1 is decided on the simplest Scheme 1 and S2-Simple comparisons first.

## Labels, splits, and leakage boundaries

- A behavior choice is behavior supervision, never Q-star or optimal-Q truth.
- Ranking requires a complete legal-action catalog and `rank_eligible=true`.
- Random actions may support dynamics and hard negatives but are not positive rank labels.
- Successor supervision requires an executed action and a real stable successor.
- Seed roots, episodes, and runs never cross train/dev/test partitions.
- Runtime-local IDs, future state, reward, outcome, teacher metadata, candidate position,
  and post-action facts are excluded from model inputs.
- Gold-dev and Gold-test have separate manifests. Gold-test stays sealed through Gates 0-4.
- B6 and the one-time Gold-test are opened only after a frozen Gate 5 candidate and explicit
  owner approval. Results never change the already-frozen candidate.

## Required controls and diagnostics

These controls are predeclared. A report must mark each one `measured`, `not_applicable`, or
`not_exercised`; omission is not a pass.

| Control | Required interpretation |
|---|---|
| Uniform random legal | Floor for decision quality; sampled only from the complete catalog. |
| Action prior / action-only | Measures behavior-frequency and action-text shortcuts. |
| State-blind | Removes state input while retaining the candidate set. |
| Candidate permutation | Scores and choice must be equivariant to catalog order. |
| Label permutation / leakage audit | Training should fail under permuted labels; direct leakage is a Gate 0 failure. |
| B4 identity successor | Calibrates successor retrieval against copying the current state. |
| State-only / no-action | Tests whether transition/value paths ignore the chosen action. |
| Wrong-action hard negative | Executed successor must prefer its actual action over declared alternatives. |
| Predicted-action collapse/spread | Reports variance and retrieval so a collapsed latent cannot look successful. |
| Same-architecture frozen random Qwen | Isolates pretrained representation value with exact seed and parameter digest. |

Useful hand-authored heuristics may be reported as declared baselines, but they are not a
teacher oracle and cannot replace Human Gold or the random/action-prior controls.

## Gates 0-5

Gates are sequential. A failed gate stops downstream scientific runs until the cause is
fixed under a new manifest. B0-B7 remain the supporting evidence families; a successor loss
or B4 result alone never establishes a decision gain.

### Gate 0 - admission

Pass only when exact source/data/Qwen/environment identities validate; B0 has zero errors;
all records have declared eligibility and provenance; splits are seed-root disjoint; leakage
and candidate-order tests pass; full-weight CUDA/BF16, deterministic extraction, cache
invalidation, frozen parameters, failure paths, latency, and VRAM are measured; and all
three model families complete forward plus backward-only engineering smokes. Gold and B6
remain sealed.

### Gate 1 - pretrained representation value

Compare paired pretrained versus random runs for Scheme 1 linear and S2-Simple N using the
same data, seeds, architecture, budget, and evaluation rows. The primary measure is
acceptable-action Top-1 on Gold-dev; B1 behavior holdout and B3 diagnostics are supporting.
Pass only if pretrained is positive for every paired seed and the paired bootstrap 95%
confidence interval lower bound is above zero. Random identity must include the exact
initialization digest. No successor metric can substitute for this comparison.

### Gate 2 - Scheme 1 viability

Freeze the stronger pretrained Scheme 1 head using train/behavior-dev only, then compare it
on Gold-dev with uniform random, action-prior/action-only, state-blind, and the declared
useful heuristic baseline. Pass only if it beats every required baseline for every seed and
the paired bootstrap 95% confidence interval lower bound is above zero against the strongest
baseline. Candidate-permutation and label-leakage diagnostics must also pass.

### Gate 3 - successor value

Compare S2-Simple Z with S2-Simple N using paired pretrained runs. Z must improve Gold-dev
acceptable-action Top-1 for every seed with a paired bootstrap 95% confidence interval lower
bound above zero. It must also improve the predeclared B4 retrieval measure while passing
identity-successor, state-only/no-action, wrong-action, and collapse/spread controls. Better
successor loss or B4 without the Gold-dev decision improvement fails this gate.

### Gate 4 - structured dynamics value

Compare pretrained S2-SDT with its matched S2-Simple variant after Gate 3 selects N or Z.
SDT passes only with a positive Gold-dev acceptable-action Top-1 difference for every seed
and a paired bootstrap 95% confidence interval lower bound above zero, while all relevant B3,
B4, and B7 diagnostics pass. A tie or a pure latent-metric gain selects S2-Simple because it
is the simpler model.

### Gate 5 - final Scheme 1 versus Scheme 2

Freeze one Scheme 1 and one Scheme 2 candidate, including checkpoints and inference
settings. Compare the same data, Standard inputs, Gold-dev rows, seeds, controls, and compute
report. The paired bootstrap 95% confidence interval decides only a clear difference; a tie
selects the lower-latency/lower-complexity candidate. After the owner approves the frozen
choice, open Gold-test once and run paired fixed-seed B6 once. Gold-test/B6 are final reports,
not tuning inputs, and an operational failure is reported rather than retried invisibly.

## B0-B7 evidence roles

- **B0** is the hard data, contract, leakage, split, and manifest admission gate.
- **B1** measures held-out behavior ranking and required simple controls.
- **B2** measures Human Gold acceptable actions, ambiguity, and agreement.
- **B3** tests state-action coupling, candidate permutation, and counterfactual sensitivity.
- **B4** explains successor/dynamics behavior and collapse; it cannot select a policy alone.
- **B5** keeps patch, Host, runtime, and Managed/Reference transfer strata separate.
- **B6** is the final paired live suite and requires owner approval.
- **B7** reports tokens, actions, latency, VRAM, cache, throughput, and GPU-hours separately.

Interpretation priority remains B6 > B2 approximately B3 > B5 > B1 > training loss, with
B4 explanatory and B0 mandatory.

## Owner-training boundary

Unit/synthetic/FakeQwen tests, real-Qwen forward/profile/backward checks, and at most two
optimizer steps for plumbing are engineering work. Any real-dataset multi-step optimization
that can produce a checkpoint or metric is owner training. Before it begins, preparation
must print and persist the exact source SHA, dataset/B0/Qwen/config identities, seed, command,
resources, output paths, pass/fail criteria, and retry rule. Codex then stops at:

`STOP - OWNER TRAINING REQUIRED: L2-TINY-OVERFIT`

The first owner run is the bounded Scheme 1 linear memorization check in
`configs/v0/experiments/l2-tiny-overfit.json`. It never uses Gold or B6 and cannot support a
scientific claim. Retries are new attempt IDs; failed artifacts and reasons are retained.
