# Current Status

## Verdict

**STPD is pre-alpha and pre-Qwen definition-of-ready is implemented.** The repository is
ready for an L2 full-weight handoff; it contains no real Qwen representation, scientific
model result, or final STPD v0 claim.

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
- immutable Qwen3-0.6B-Base metadata/tokenizer L1 pin and weight-rejecting cache inspection;
- DeterministicFakeQwenBackend engineering path across all three model families;
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

## Non-claims and remaining L2 work

- FakeQwen is not a random-initialized scientific control and proves no representation quality.
- Full Qwen weights were not downloaded or loaded; frozen-Qwen latency/VRAM are unmeasured.
- No Human Gold, B1-B7 scientific result, 30-run core matrix, v0 winner or policy claim exists.
- The bounded transition sample is not a production corpus or broad semantic qualification.
- Natural selector token families, large-corpus near-duplicate analysis and scientific data
  admission remain future dataset work.
- Formal H1.0 long soak, broad CrossHost/fault/cross-platform campaigns remain deferred.

The next material step is the pinned full-weight/GPU L2 implementation and experiment lane.
See [Pre-Qwen Operations](PRE_QWEN_OPERATIONS.md), [Roadmap](ROADMAP.md), and
[Qwen L1 Handoff](QWEN_L1_HANDOFF.md).
