# Current Status

## Verdict

**STPD is pre-alpha; full-weight Qwen L2, bounded tiny-overfit engineering admission,
the 1,962-record unified Human corpus Gate-0 lane, and the owner-run S1 behavior smoke are
complete. The exact trained checkpoint has an experimental live Connector lane;
scientific Core remains blocked by missing Human Gold.**
The repository contains a real frozen pretrained backend and same-architecture random
control, but no scientific Core model result, Human Gold result, B6 result, or final STPD
v0 claim.

## Exact environment lane

| Layer | Current identity |
|---|---|
| Game | macOS arm64 STS2 `v0.111.0/41cef1ea`, assembly `9cb4f1a.../57785517...` |
| Host Runtime code | Platform package `1.1.0-rc.4`, source `5c5ceaf...`, tree `94228f9...`, package `5ec4ed1...` |
| Managed candidate | predecessor operational artifact `8dc622b0.../7228541c...`; platform-specific candidates remain independently audited |
| Managed Host | upstream `d11aa883...`, macOS patch `8ced088b...`, artifact `8dc622b0.../7228541c...` |
| Connector Reference | `v1.1.0-rc.1/e065102...`, artifact `c1877f1a.../64765ea1...` |
| Player Environment | protocol `1.0.0`; Platform SDK package `1.1.0-rc.1`, policy `player_visible_v1` |

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

Four audited HumanSession bundles are admitted: one macOS session with 775
records and three Windows sessions with 16, 407 and 764 records. Seven other
Windows recording directories remain preserved but rejected because their
decision record file is absent. No raw evidence was edited. The admitted
population contains 1,962 exact-unique decisions across 14 whole runs: 1,571
card plays and 391 end turns, with 775 macOS and 1,187 Windows records.

The `human-combat-unified-v2` plan combines only immutable profile corpora and
globally reruns collision/deduplication, semantic-component/root-safe splitting,
B0 and token profiling. It reports zero exact duplicates, zero semantic duplicate
groups and zero cross-split leakage; train/dev/test contain 11/1/2 whole runs.
Serializer v1 retains the complete evidence but removes the redundant Standard
combat referent rendering. Standard profiling covers 11,348 state/action samples
and passes unchanged limits at P95 2,883 and max 4,110 tokens. B0 passes all
1,962 records. The final local READY artifact binds the exact clean source,
corpus and Qwen identities after all tracked changes are committed.

The owner-run `S1-1K-2K-SMOKE` completed 1,659 steps from source
`caddbcc71a990b5d0970c0bf574823f16d501eb2`. Final checkpoint SHA-256 is
`c70c482ca1af52c9dc5477a45623f7ad531222400ba6eefd3c17c87b7cc922d3`;
checkpoint identity is `4da5b472371330b0a6b7257f5998b079516055751f2ddea5755ce1d720249c64`.
Behavior-dev mean listwise NLL changed from `1.7769335006` to `1.2975336015`
and Top-1 from `0.3421052632` to `0.4473684211`. This passes only the frozen
behavior engineering smoke criteria and makes no policy-quality or Core claim.

The experimental live v1 lane loads that checkpoint with the exact frozen Qwen,
serializer v1, Standard input and Scheme1 linear head. It uses Connector SDK
package `1.1.0-rc.1` from the immutable Platform release as strict transport
decoder; the exact loaded Connector remains the sole action authority. The lane
admits only whole complete Defect A0
ordinary-Combat catalogs containing `play`/`end_turn`, under the exact
Connector-only Modset `44f2fdce...`. Unsupported catalogs and
unknown delivery fail closed; local Receipts/successors/handoffs are append-only
under `.local/live-s1/`.
Transient HTTP 409 `stale_state` races during Snapshot-bound Read prefetch now
discard and refresh the whole observation transaction with bounded backoff;
they do not weaken coherence or taint an otherwise safe Human/Qwen handoff.
The live bridge preserves Connector Reads as a multi-instance array instead of
keying by kind. A full provenance audit found 39 per-card `surface_card`
descriptors across 10 accepted successor frames, but Human import projected
all 1,962 state/successor pairs with `reads={}` and serializer v1 emitted no
`READS=` training lines. Live S1 therefore explicitly prefetches the exact empty
checkpoint Read subset while retaining advertised descriptors in Snapshot evidence.

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
No AgenticSTS extractor or training dataset was created; the S1 smoke instead uses the
strictly admitted unified Human corpus.

## Non-claims and remaining work

- Tiny-overfit attempts prove neither pretrained advantage nor policy quality; they are
  optimizer/memorization-plumbing evidence only.
- No Human Gold, B1-B7 scientific result, 30-run Core matrix, v0 winner or policy claim exists.
- The bounded ranking fixture is not a production corpus or broad semantic qualification.
- Historical AgenticSTS states do not authorize reconstructing missing legality, seeds,
  successors, or current-patch identities.
- Natural selector action families remain unsupported and were not admitted.
- Human Gold is unavailable, so scientific Core and Gold/B6 remain blocked even
  though the behavior S1 smoke completed.
- Annotator audit and explicit owner attestation do not machine-prove operator
  identity or non-interference. Existing owner-completed sessions validate only
  the exact ordinary-combat source envelope, not other workers, platforms or
  unsupported families.

The immediate bounded step is an owner-operated experimental Human + Qwen live
smoke; do not interpret it as Core/B6 or open Gold-test. See the
[AgenticSTS audit](evidence/AGENTICSTS_DATA_ADMISSION_AUDIT_2026-08-22.md),
[Data and Provenance](DATA_AND_PROVENANCE.md), and [Roadmap](ROADMAP.md).
