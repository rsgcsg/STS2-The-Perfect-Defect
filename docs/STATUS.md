# Current Status

## Verdict

**STPD is pre-alpha; full-weight Qwen L2 and bounded tiny-overfit engineering admission are
complete. AgenticSTS remains blocked at data admission, while the exact Human Corpus lane
is implemented but remains below the current 1,500-row campaign target.**
The repository contains a real frozen pretrained backend and same-architecture random
control, but no scientific Core model result, Human Gold result, B6 result, or final STPD
v0 claim.

## Exact environment lane

| Layer | Current identity |
|---|---|
| Game | macOS arm64 STS2 `v0.111.0/41cef1ea`, assembly `9cb4f1a.../57785517...` |
| Headless | release `v1.0.1`, source `4961b52...` operational baseline; later Windows/source closeout is separately versioned |
| Managed Host | upstream `d11aa883...`, macOS patch `8ced088b...`, artifact `8dc622b0.../7228541c...` |
| Connector Reference | `v1.1.0-rc.1/e065102...`, artifact `c1877f1a.../64765ea1...` |
| Player Environment | protocol/SDK `1.0.0/1.0.0`, policy `player_visible_v1` |

Windows x64 has separate candidate evidence for game `v0.111.0/41cef1ea`; it does not
inherit the macOS operational freeze or formal H1.0 authority.

## Implemented and tested before owner training

- Python 3.11-only `uv` lock, CI/package, canonical docs and strict schemas;
- ResearchState/Action/Transition, deterministic Lite/Standard/Full serialization and B0;
- canonical Parquet/manifests/splits/dedup and fail-closed provenance handling;
- fail-closed Human Annotator import through the existing research projection,
  whole-run split, canonical Parquet and B0 path;
- versioned exact Human Collection Profiles, immutable checksummed session
  bundles, pseudonymous multi-worker registry, strict multi-session corpus
  admission, whole-run/semantic-component splits, multi-source provenance,
  immutable corpus snapshots, Standard token profiling and frozen smoke handoff;
- an independent exact Windows x64 human collection profile/campaign bound to
  the cold-loaded game, Connector, Annotator and observer Modset identities;
- a thin final cross-profile merger that consumes only admitted immutable
  snapshots, preserves nested provenance and globally reruns collision/dedup,
  whole-run splitting, B0 and Standard profiling;
- Scheme 1, S2-Simple and S2-SDT with ranking/successor/anchor objectives;
- optimizer/checkpoint/evaluation mechanics and B1-B7 report/gate tooling;
- immutable Qwen3-0.6B-Base L1/L2 pin, exact full-weight CUDA/BF16 backend and random control;
- deterministic real-Qwen representation, VRAM/latency and all-three-family backward-only smokes;
- frozen 10-configuration/three-seed Core matrix, controls, Gates 0-5 and Gold/B6 boundary.

## Runtime and engineering evidence

A bounded exact Managed collection reached natural game over with 10 Combat transitions,
complete finite action catalogs, exact Receipts/successors, complete `run_deck` and
`combat_piles` Reads, canonical Parquet and B0 pass. The pinned tokenizer profile contains
180 `turn_action` joint samples: Full max/P95 `3334/3334`, Lite and Standard `2501/2501`.
Natural `card_selection` and `card_choice` were not exercised.

The Native Human Annotator current exact artifact has owner-completed local
ordinary-combat evidence. Its latest session contains 28 exact-unique records
(14 targeted plays, 9 untargeted plays, 5 end turns), 28 different stable
successors, zero invalid records and one correctly isolated overlapping-action
invalidation. An earlier same-artifact 20-record export passed strict STPD import
and B0. These are local human-source facts. The bundle/corpus lane now has one
single-worker offline canary; additional real workers and sessions remain
required before it can reach the campaign target.

The first real bundle/corpus canary used the closed 20-record exact session.
Bundle content `3a5b1241...` and export `e59321b9...` registered idempotently;
strict multi-session admission accepted 20/20, canonical Parquet and corpus B0
passed, one whole run remained in one split, and no exact/semantic duplicate
crossed a split. The report correctly recovered 8 targeted plays, 8 untargeted
plays and 4 end turns. Standard profiling expanded the 20 decisions across 159
legal state/action pairs and failed its unchanged P95 gate at `4907 > 4096`
(max 5478, hard limit 8192). The campaign target is 1,500 accepted records, so
the frozen smoke handoff correctly remains unavailable for both independent
reasons. This canary was built by STPD source `e0a0334...`; later documentation
commits do not transfer its evidence to another source identity.

The second same-profile bundle (`cf57b6b1...`, export `55885767...`) registered
idempotently and expanded the latest offline macOS corpus to 48 accepted rows
across two sessions and two whole runs. Corpus `291afe89...` passes strict
admission and B0 with zero exact/semantic duplicates; it contains 22 targeted
plays, 17 untargeted plays and 9 end turns. Its unchanged Standard profile still
fails at P95 `4806 > 4096` (max 5478), and 1,452 rows remain to the 1,500-row
target. This is offline corpus evidence, not training authorization.

On Windows, exact Qwen revision `da87bfb...` loaded 596,049,920 pretrained parameters on
CUDA/BF16. Synthetic 1,024-token extraction measured 0.145 seconds and 1,394,181,120 bytes
peak allocated VRAM on the RTX 4070 Laptop GPU. These remain engineering smokes only.

## Owner L2-TINY-OVERFIT attempts

Attempt-001, original 64-step budget:

```text
initial mean NLL       1.7887210548
final mean NLL         0.9022365957
relative reduction     49.5596816%
memorized Top-1        25% -> 100%
finite values          pass
Qwen gradients         absent/pass
elapsed                27.8884 s
status                 fail
```

Attempt-002, protocol-r1 256-step budget:

```text
initial mean NLL       1.7887210548
final mean NLL         0.2385502681
relative reduction     86.6636406%
memorized Top-1        100%
finite values          pass
Qwen gradients         absent/pass
elapsed                17.9047 s
status                 fail
```

Attempt-002 intermediate NLL:

```text
64   0.9022365957
128  0.5347326919
192  0.3452932015
256  0.2385502681
```

Attempt-003, protocol-r2 512-step budget:

```text
initial mean NLL       1.7887210548
final mean NLL         0.0850893874
relative reduction     95.2430041%
memorized Top-1        100%
finite values          pass
Qwen gradients         absent/pass
elapsed                17.9055 s
status                 pass
```

All unchanged criteria passed. Attempts 001 and 002 remain retained failures; attempt 003
is the successful optimizer/memorization-plumbing admission. The three local result files
are bound respectively to exact sources
`a95ab022b8d81e6e697e8784893ece9c5eb1f59d`,
`d837edeb82958fc115143d34c969e90b62cf8d19`, and
`938199aec4768f27c7231a26335abe66f2d8d12e`; they are not overwritten or relabelled.

This resolves only the tiny-overfit engineering admission. It does not pass Gate 1, establish
pretrained representation value, or justify any architecture/model-quality claim.

## AgenticSTS data-admission audit

The official `AlayaLab/AgenticSTS-trajectories` subset was pinned at immutable revision
`20f5170c420584935ec20e004498b4d4a3621f8b`. Its `trajectories/` and
`runs_history.jsonl` scope is CC-BY-4.0; mixed-license competitor archives remain excluded.

Every one of the 305 available trajectory logs was audited. They contain 198,600 decision
events, including 139,211 combat decisions with reconstructable player-visible states.
However, there are zero explicit complete legal-action catalogs, zero game seeds, zero
exact environment identities, and therefore zero rank-eligible accepted rows (`0.0%`).
No extractor, Parquet dataset, split manifest, S1 smoke config, or owner command was created.

## Non-claims and remaining work

- Tiny-overfit attempts prove neither pretrained advantage nor policy quality; they are
  optimizer/memorization-plumbing evidence only.
- No Human Gold, B1-B7 scientific result, 30-run Core matrix, v0 winner or policy claim exists.
- The bounded ranking fixture is not a production corpus or broad semantic qualification.
- Historical AgenticSTS states do not authorize reconstructing missing legality, seeds,
  successors, or current-patch identities.
- Natural selector token families, large-corpus near-duplicate analysis and scientific data
  admission remain future work.
- Real Standard representation size exceeds the current P95 token gate on the
  first Human corpus canary. Do not raise the threshold or truncate to force a
  pass; representation/pin ownership needs a separate evidence-based decision.
- Annotator audit and explicit owner attestation do not machine-prove operator
  identity or non-interference. Existing owner-completed sessions validate only
  the exact ordinary-combat source envelope, not other workers, platforms or
  unsupported families.

The immediate next step is to pack/register the current exact session, verify
the deterministic corpus/B0/token-profile lane offline, then collect additional
exact-profile sessions until at least 1,500 complete-catalog, whole-root behavior
decisions exist. See the
[AgenticSTS audit](evidence/AGENTICSTS_DATA_ADMISSION_AUDIT_2026-08-22.md),
[Data and Provenance](DATA_AND_PROVENANCE.md), and [Roadmap](ROADMAP.md).
