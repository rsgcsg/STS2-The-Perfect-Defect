# Current Status

## Verdict

**STPD is pre-alpha; full-weight Qwen L2 engineering admission is complete, one bounded
owner tiny-overfit attempt has run, and protocol r1 is prepared for an owner-authorized
retry.** The repository contains a real frozen pretrained backend and same-architecture
random control, but no scientific Core model result, Human Gold result, B6 result, or final
STPD v0 claim.

## Exact environment lane

| Layer | Current identity |
|---|---|
| Game | macOS arm64 STS2 `v0.111.0/41cef1ea`, assembly `9cb4f1a.../57785517...` |
| Headless | release `v1.0.1`, source `4961b52...` operational baseline; later Windows/source closeout is separately versioned |
| Managed Host | upstream `d11aa883...`, macOS patch `8ced088b...`, artifact `8dc622b0.../7228541c...` |
| Connector Reference | `v1.1.0-rc.1/e065102...`, artifact `c1877f1a.../64765ea1...` |
| Player Environment | protocol/SDK `1.0.0/1.0.0`, policy `player_visible_v1` |

This is an operational STPD baseline, not formal H1.0 qualification. Headless `v1.0.0`
used a different Managed artifact; its runtime evidence is predecessor-only.

Windows x64 has separate candidate evidence for game `v0.111.0/41cef1ea`. These candidates
do not inherit the macOS operational freeze or formal H1.0 authority.

## Implemented and tested before owner training

- Python 3.11-only `uv` lock, CI, package build, canonical docs and strict schemas;
- ResearchState/Action/Transition, execution-envelope separation and eligibility;
- deterministic Lite/Standard/Full ModelState plus ModelAction, semantic hashes, golden
  fixtures and leakage rejection;
- raw JSONL to canonical Parquet, checksummed manifests, seed-root split/dedup and B0;
- fail-closed AgenticSTS audit/import with source-subset license/provenance admission;
- source-free Player Environment projection and current Managed stable-transition collector;
- trainable Scheme 1, S2-Simple and S2-SDT with ranking/successor/anchor objectives;
- RankBatch/DynamicsBatch optimizer steps, atomic identity-bound checkpoint/resume and
  independent ranking evaluation;
- B1-B7 report/gate mechanics with synthetic positive and negative evidence;
- immutable Qwen3-0.6B-Base metadata/tokenizer L1 pin and full-weight L2 file pin;
- offline exact-snapshot inspection, explicit fetch/discovery, frozen CUDA/BF16 pretrained
  backend, same-architecture seeded random control, and checksum-keyed CPU feature cache;
- deterministic real-Qwen representation, VRAM/latency, and all-three-family backward-only
  smokes with no Qwen gradients;
- DeterministicFakeQwenBackend cheap engineering path across all three model families;
- exact 10-configuration/three-seed scientific Core matrix, controls, Gates 0-5 and
  Gold/B6 boundary;
- checksum-bound artifact manifest, pre-Qwen doctor and path-free L2 handoff manifest.

## Runtime and engineering evidence

A bounded exact Managed collection reached natural game over with 10 Combat transitions,
complete finite action catalogs, exact Receipts/successors, complete `run_deck` and
`combat_piles` Reads, provenance pass, canonical Parquet and B0 pass. The pinned tokenizer
profile contains 180 `turn_action` joint samples: Full max/P95 `3334/3334`, Lite and
Standard `2501/2501`. Natural `card_selection` and `card_choice` were not exercised, so the
aggregate token gate is not claimed passed.

On Windows, exact Qwen revision `da87bfb...` loaded 596,049,920 pretrained parameters on
CUDA/BF16. Synthetic 1,024-token extraction measured 0.145 seconds and 1,394,181,120 bytes
peak allocated VRAM on the RTX 4070 Laptop GPU. Two independent full random constructions
at seed `20260822` matched fingerprint `2db01fbe...`. These are engineering smokes only.

### Owner-reported L2-TINY-OVERFIT attempt-001

The repository owner ran the original 64-step bounded Scheme 1 linear memorization check
from source `a95ab022b8d81e6e697e8784893ece9c5eb1f59d`, using preparation SHA-256
`7da5ad0bf8df8c422f2affeaf6a89fb041231aac2a0d59709228c6311253302e`.
The local result reported:

```text
initial mean listwise NLL      1.7887210548
final mean listwise NLL        0.9022365957
relative loss reduction        49.5596816%
memorized Top-1                25% -> 100%
finite values                  pass
Qwen gradient tensor count     pass
elapsed                        27.8884 s
status                         fail
```

The failure is retained because the predeclared final NLL <= 0.1 and relative reduction >=
90% thresholds were not met. The owner-inspected trace continued decreasing smoothly through
step 64, so protocol r1 classifies the immediate retry question as an under-budgeted
engineering memorization test, not as demonstrated training-plumbing failure. This is
user-reported local evidence and is not a scientific quality result.

Protocol `stpd-v0-l2-2026-08-22-r1` changes only the tiny-overfit retry budget to 256 steps
and prepares `attempt-002`; pass criteria, data-selection rule, Qwen, model, seed, optimizer,
learning rate, Core matrix, Gold/B6 boundaries and Gates remain unchanged.

## Non-claims and remaining L2 work

- Attempt-001 proves neither pretrained advantage nor policy quality; it is an optimizer and
  memorization-plumbing check only.
- FakeQwen remains non-scientific; the real random-Qwen control has no quality claim before
  paired admitted-data evaluation.
- No Human Gold, B1-B7 scientific result, 30-run Core matrix, v0 winner or policy claim exists.
- The bounded transition/ranking fixture is not a production corpus or broad semantic
  qualification.
- Natural selector token families, large-corpus near-duplicate analysis and scientific data
  admission remain future dataset work.
- Formal H1.0 long soak, broad CrossHost/fault/cross-platform campaigns remain deferred.

The immediate next step is to pull protocol r1, regenerate a clean-source tiny-overfit
preparation against the same admitted local dataset/Qwen artifact, stop for owner
authorization, and execute only the prepared `attempt-002` command. See
[Qwen L2 Operations](QWEN_L2_OPERATIONS.md),
[Scientific Experiment Protocol](SCIENTIFIC_EXPERIMENT_PROTOCOL.md), and
[Roadmap](ROADMAP.md).
