# Qwen L2 Operations And Owner Handoff

## Current verdict

The exact full-weight `Qwen/Qwen3-0.6B-Base` snapshot is admitted outside Git for
offline CUDA/BF16 engineering use. Pretrained and same-architecture frozen random
controls pass deterministic feature extraction and backward-only integration with Scheme
1, S2-Simple, and S2-SDT. This is not a representation-quality claim.

Two bounded owner-run tiny-overfit attempts have now occurred. The original 64-step
`attempt-001` and the 256-step `attempt-002` both reached 100% memorized Top-1, remained
numerically finite, kept Qwen frozen, and continued reducing loss through their final step.
They failed only the unchanged final-NLL and relative-loss-reduction thresholds. Protocol r2
therefore makes one final budget-only retry at 512 optimizer steps as `attempt-003`.

## Immutable identity

- model and tokenizer revision:
  `da87bfb608c14b7cf20ba1ce41287e8de496c0cd`;
- `model.safetensors`: 1,192,135,096 bytes, SHA-256
  `cd2a512003e2f9f3cd3c32a9c3573f820bb28c940f73c57b1ddaa983d9223eba`;
- architecture: `Qwen3ForCausalLM`, 596,049,920 parameters, hidden size 1,024;
- dtype/device: BF16 on explicit `cuda:0`, detached float32 features;
- attention/cache: eager attention, generation cache disabled;
- pooling/joint format: `masked-mean-v0` and `state-newline-action-v0`;
- no silent truncation and no Qwen gradients.

The checked-in pin and every snapshot file hash are authoritative. The local cache path
is operational input and must never be committed.

## Rebuild and inspect

```powershell
uv sync --locked --all-extras
uv run python tools/qwen_l2.py inspect --cache-dir "$env:USERPROFILE\.cache\stpd\qwen-l2" --output .local/evidence/l2/qwen-inspect.json
```

`inspect` and all backend loads are offline and fail closed on missing, unexpected, resized,
or rehashed files.

## Engineering smokes

```powershell
uv run python tools/l2_smoke.py --cache-dir "$env:USERPROFILE\.cache\stpd\qwen-l2" --control pretrained --output .local/evidence/l2/pretrained-smoke.json
uv run python tools/l2_smoke.py --cache-dir "$env:USERPROFILE\.cache\stpd\qwen-l2" --control random --random-seed 20260822 --output .local/evidence/l2/random-smoke.json
```

On the admitted Windows host, pretrained Qwen loaded in 1.339 seconds; a synthetic
1,024-token forward took 0.145 seconds with 1,394,181,120 bytes peak allocated VRAM. All
three model families produced finite losses and trainable-head gradients with zero Qwen
gradients. These are synthetic engineering checks only.

## Bounded real-data preparation

Preparation replays data/B0/Qwen/config/source identities and writes the exact owner command
without constructing an optimizer:

```powershell
uv run python tools/l2_tiny_overfit.py prepare --dataset-manifest <MANIFEST> --qwen-cache <QWEN_CACHE> --output .local/evidence/l2/tiny-overfit-preparation-<NEW-SHA>-r2
```

It must stop with:

`STOP - OWNER TRAINING REQUIRED: L2-TINY-OVERFIT`

Do not invoke the `run` subcommand without the repository owner's explicit authorization.

## Attempt history and active r2 retry

`attempt-001`, 64 steps:

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

`attempt-002`, 256 steps:

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

Owner-reported intermediate NLL for attempt-002:

```text
step 64   0.9022365957
step 128  0.5347326919
step 192  0.3452932015
step 256  0.2385502681
```

The active config is protocol `stpd-v0-l2-2026-08-22-r2` and keeps exactly the same data
selection, Scheme 1 linear model, Standard input, pretrained frozen Qwen, seed `20260822`,
AdamW, learning rate `0.001`, weight decay `0.0`, grad clip `1.0`, and pass thresholds. Only
the bounded budget changes to 512 optimizer steps with checkpoints at 0 and 512. A new
preparation emits `attempt-003`.

Attempt-003 is the final default budget-only retry. If it still fails, do not automatically
increase to 1024/2048 steps. Audit fixture design, linear-feature separability, optimizer
behavior and related plumbing first.

See [Scientific Experiment Protocol](SCIENTIFIC_EXPERIMENT_PROTOCOL.md) for the exact
revision history, frozen 10-configuration/three-seed matrix, controls, Gates 0-5, and
interpretation boundary.
