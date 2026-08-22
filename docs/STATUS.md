# Current Status

## Verdict

**STPD is pre-alpha; full-weight Qwen L2 engineering admission and the scientific
protocol are implemented.** The repository contains a real frozen pretrained backend and
same-architecture random control, but no owner training, scientific model result, Gold
test, B6 result, or final STPD v0 claim.

## Exact environment lane

| Layer | Current identity |
|---|---|
| Game | macOS arm64 STS2 `v0.111.0/41cef1ea`, assembly `9cb4f1a.../57785517...` |
| Headless | release `v1.0.1`, source `4961b52...` |
| Managed Host | upstream `d11aa883...`, patch `8ced088b...`, artifact `8dc622b0.../7228541c...` |
| Connector Reference | `v1.1.0-rc.1/e065102...`, artifact `c1877f1a.../64765ea1...` |
| Player Environment | protocol/SDK `1.0.0/1.0.0`, policy `player_visible_v1` |

This is an operational STPD baseline, not formal H1.0 qualification. Headless `v1.0.0`
used a different Managed artifact; its runtime evidence is predecessor-only.

Windows x64 has separate candidate evidence for game `v0.111.0/41cef1ea`: Headless
Managed Host `0d8c9163.../387bc1a3...` and Connector current-source Host
`2050ae23.../64066c98...`. These candidates do not inherit the macOS operational freeze or
formal H1.0 authority.

## Implemented and tested

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
- frozen 10-configuration/three-seed scientific protocol, controls, Gates 0-5, Gold/B6
  boundary, and bounded owner-gated L2 tiny-overfit preparation/run tooling;
- checksum-bound artifact manifest, pre-Qwen doctor and path-free L2 handoff manifest.

## Runtime evidence

A bounded exact Managed collection reached natural game over with 10 Combat transitions,
complete finite action catalogs, exact Receipts/successors, complete `run_deck` and
`combat_piles` Reads, provenance pass, canonical Parquet and B0 pass. The pinned tokenizer
profile contains 180 `turn_action` joint samples: Full max/P95 `3334/3334`, Lite and
Standard `2501/2501`. Natural `card_selection` and `card_choice` were not exercised, so the
aggregate token gate is not claimed passed.

Headless `v1.0.1` current-artifact gates additionally passed exact audit, native binding,
two terminal episodes (346 deliveries, 633 Reads), stale/reset/idempotency and
unknown-no-retry process replacement. Connector RC and Headless releases are publicly
downloadable; a cold Headless clone reproduced the exact Host SHA/MVID.

On Windows, exact Qwen revision `da87bfb...` loaded 596,049,920 pretrained parameters on
CUDA/BF16. Synthetic 1,024-token extraction measured 0.145 seconds and 1,394,181,120 bytes
peak allocated VRAM on the RTX 4070 Laptop GPU. Two independent full random constructions
at seed `20260822` matched fingerprint `2db01fbe...`. These are engineering smokes only.

## Non-claims and remaining L2 work

- FakeQwen remains non-scientific; the real random-Qwen control has no quality claim before
  paired admitted-data evaluation.
- Synthetic real-Qwen smokes prove implementation, determinism, resource measurement, and
  frozen-gradient boundaries only; they prove no pretrained advantage.
- No Human Gold, B1-B7 scientific result, 30-run core matrix, v0 winner or policy claim exists.
- The bounded transition sample is not a production corpus or broad semantic qualification.
- Natural selector token families, large-corpus near-duplicate analysis and scientific data
  admission remain future dataset work.
- Formal H1.0 long soak, broad CrossHost/fault/cross-platform campaigns remain deferred.

The next material step is a clean-source bounded Managed ranking fixture and exact
preparation manifest. Execution must then stop for explicit owner authorization before the
first 64-step real-data tiny overfit. See [Qwen L2 Operations](QWEN_L2_OPERATIONS.md),
[Scientific Experiment Protocol](SCIENTIFIC_EXPERIMENT_PROTOCOL.md), and
[Roadmap](ROADMAP.md).
