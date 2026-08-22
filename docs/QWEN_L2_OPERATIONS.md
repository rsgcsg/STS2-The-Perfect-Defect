# Qwen L2 Operations And Owner Handoff

## Current verdict

The exact full-weight `Qwen/Qwen3-0.6B-Base` snapshot is admitted outside Git for
offline CUDA/BF16 engineering use. Pretrained and same-architecture frozen random
controls pass deterministic feature extraction and backward-only integration with Scheme
1, S2-Simple, and S2-SDT. This is not a representation-quality claim.

One bounded owner-run tiny-overfit attempt has now occurred. The original 64-step
`attempt-001` reached 100% memorized Top-1 but failed the unchanged final-NLL and relative
loss-reduction thresholds while its loss was still decreasing. Protocol r1 therefore keeps
the same data/model/Qwen/optimizer/pass criteria and increases only the bounded retry budget
to 256 optimizer steps. The retry remains owner-gated and is not a scientific model result.

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

Install the locked environment, then explicitly discover/fetch or inspect the snapshot:

```powershell
uv sync --locked --all-extras
uv run python tools/qwen_l2.py discover --output .local/evidence/l2/qwen-discovery.json
uv run python tools/qwen_l2.py fetch --cache-dir "$env:USERPROFILE\.cache\stpd\qwen-l2" --output .local/evidence/l2/qwen-fetch.json
uv run python tools/qwen_l2.py inspect --cache-dir "$env:USERPROFILE\.cache\stpd\qwen-l2" --output .local/evidence/l2/qwen-inspect.json
```

`discover` and `fetch` are explicit online operations. `inspect` and all backend loads are
offline and fail closed on missing, unexpected, resized, or rehashed files.

## Engineering smokes

Run pretrained and random controls separately:

```powershell
uv run python tools/l2_smoke.py --cache-dir "$env:USERPROFILE\.cache\stpd\qwen-l2" --control pretrained --output .local/evidence/l2/pretrained-smoke.json
uv run python tools/l2_smoke.py --cache-dir "$env:USERPROFILE\.cache\stpd\qwen-l2" --control random --random-seed 20260822 --output .local/evidence/l2/random-smoke.json
```

On the admitted Windows host, pretrained Qwen loaded in 1.339 seconds; a synthetic
1,024-token forward took 0.145 seconds with 1,394,181,120 bytes peak allocated VRAM. All
three model families produced finite losses and trainable-head gradients with zero Qwen
gradients. Two independent full random constructions at seed `20260822` produced exact
parameter fingerprint
`2db01fbe8292c68fa485c9f4e4d5a9f083c0ecfe030685b65248965c73be07df`.

These are synthetic engineering checks. They do not establish pretrained advantage or a
scientific winner.

## Bounded real-data preparation

The current Managed collector defaults to transition-only records. For the deliberately
transparent tiny-overfit plumbing fixture, `canonical-semantic-first` may mark the actual
canonical first behavior action against a complete action catalog as full-listwise rank
supervision:

```powershell
uv run python tools/collect_managed.py --headless <HEADLESS_REPO> --candidate <EXACT_CANDIDATE> --output .local/evidence/l2/managed-ranking-fixture --seed <SEED> --max-environment-actions 64 --max-transitions 8 --split-salt stpd-l2-tiny-overfit-v0 --tokenizer-cache <L1_TOKENIZER_CACHE> --ranking-supervision canonical-semantic-first
```

This mode is not a teacher, Q-value, reward, quality label, or policy claim. Preparation
replays schema, byte hashes, semantic hashes, split assignments, B0, rank eligibility,
selected rows, full Qwen identity, CUDA/BF16, resources, config, and clean Git identity:

```powershell
uv run python tools/l2_tiny_overfit.py prepare --dataset-manifest <COLLECTION_OUTPUT>\dataset\manifest.json --qwen-cache "$env:USERPROFILE\.cache\stpd\qwen-l2" --output .local/evidence/l2/tiny-overfit-preparation-<NEW-SHA>-r1
```

Preparation constructs no optimizer and writes no checkpoint. It prints and persists the
exact owner command, artifacts, pass/fail criteria, and retry rule, followed by:

`STOP - OWNER TRAINING REQUIRED: L2-TINY-OVERFIT`

Do not invoke the `run` subcommand without the repository owner's explicit authorization.

## Attempt-001 and active r1 retry

The original owner-run `attempt-001` used the v0 budget of 64 optimizer steps. The
owner-reported result was:

```text
initial mean NLL       1.7887210548
final mean NLL         0.9022365957
relative reduction     49.5596816%
memorized Top-1        25% -> 100%
finite values          pass
Qwen gradients         absent/pass
elapsed                27.8884 s
```

The loss remained smoothly decreasing through step 64. The original attempt remains a
failed engineering artifact because the unchanged criteria require final mean NLL <= 0.1
and relative reduction >= 90%.

The active config at `configs/v0/experiments/l2-tiny-overfit.json` is protocol
`stpd-v0-l2-2026-08-22-r1`. It uses exactly:

```text
2-4 rank-eligible train examples
Scheme 1 linear
Standard input
pretrained frozen Qwen
seed 20260822
AdamW
learning_rate 0.001
weight_decay 0.0
grad_clip_norm 1.0
256 optimizer steps
checkpoint steps 0 and 256
same pass/fail thresholds as attempt-001
```

A new preparation under r1 emits `attempt-002`. It must be generated from a clean pulled
source and a new output directory; it never overwrites the old local attempt-001 directory.

See [Scientific Experiment Protocol](SCIENTIFIC_EXPERIMENT_PROTOCOL.md) for the exact
revision history, frozen 10-configuration/three-seed matrix, controls, Gates 0-5, and
interpretation boundary.
