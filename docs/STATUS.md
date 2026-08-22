# Current Status

## Verdict

**STPD is pre-alpha; full-weight Qwen L2 engineering admission is complete, two bounded
owner tiny-overfit attempts have run, and protocol r2 is prepared for one final
owner-authorized budget-only retry.** The repository contains a real frozen pretrained
backend and same-architecture random control, but no scientific Core model result, Human
Gold result, B6 result, or final STPD v0 claim.

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

On Windows, exact Qwen revision `da87bfb...` loaded 596,049,920 pretrained parameters on
CUDA/BF16. Synthetic 1,024-token extraction measured 0.145 seconds and 1,394,181,120 bytes
peak allocated VRAM on the RTX 4070 Laptop GPU. These remain engineering smokes only.

## Owner-reported L2-TINY-OVERFIT attempts

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

Owner-reported attempt-002 intermediate NLL:

```text
64   0.9022365957
128  0.5347326919
192  0.3452932015
256  0.2385502681
```

The curve was still decreasing at step 256 with no observed plateau. Protocol
`stpd-v0-l2-2026-08-22-r2` therefore changes only the bounded retry budget to 512 steps and
prepares `attempt-003`. Data selection, Qwen, Scheme 1 linear, Standard input, seed, AdamW,
learning rate `0.001`, grad clip, pass criteria, Core matrix, Gold/B6 boundaries and Gates
remain unchanged.

Attempt-003 is the final default budget-only retry. If it still fails, do not automatically
increase the budget again; audit fixture design, linear-feature separability and optimizer
behavior first.

## Non-claims and remaining work

- Tiny-overfit attempts prove neither pretrained advantage nor policy quality; they are
  optimizer/memorization-plumbing evidence only.
- No Human Gold, B1-B7 scientific result, 30-run Core matrix, v0 winner or policy claim exists.
- The bounded ranking fixture is not a production corpus or broad semantic qualification.
- Natural selector token families, large-corpus near-duplicate analysis and scientific data
  admission remain future work.

The immediate next step is to pull protocol r2, regenerate a clean-source tiny-overfit
preparation against the same admitted local dataset/Qwen artifact, and execute only the
prepared `attempt-003` owner command. See [Qwen L2 Operations](QWEN_L2_OPERATIONS.md),
[Scientific Experiment Protocol](SCIENTIFIC_EXPERIMENT_PROTOCOL.md), and
[Roadmap](ROADMAP.md).
