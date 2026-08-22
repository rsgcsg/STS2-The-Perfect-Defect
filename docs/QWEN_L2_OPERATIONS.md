# Qwen L2 Operations And Owner Handoff

## Current verdict

The exact full-weight `Qwen/Qwen3-0.6B-Base` snapshot is admitted outside Git for
offline CUDA/BF16 engineering use. Pretrained and same-architecture frozen random
controls pass deterministic feature extraction and backward-only integration with Scheme
1, S2-Simple, and S2-SDT. This is not a training result or representation-quality claim.

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

These are synthetic engineering checks. They do not use an optimizer step, research
dataset, checkpoint, Gold test, B6, or a scientific comparison.

## Bounded real-data preparation

The current Managed collector defaults to transition-only records. For the deliberately
transparent tiny-overfit plumbing fixture, `canonical-semantic-first` may mark the actual
canonical first behavior action against a complete action catalog as full-listwise rank
supervision:

```powershell
uv run python tools/collect_managed.py --headless <HEADLESS_REPO> --candidate <EXACT_CANDIDATE> --output .local/evidence/l2/managed-ranking-fixture --seed <SEED> --max-environment-actions 64 --max-transitions 8 --split-salt stpd-l2-tiny-overfit-v0 --tokenizer-cache <L1_TOKENIZER_CACHE> --ranking-supervision canonical-semantic-first
```

This mode is not a teacher, Q-value, reward, quality label, or policy claim. Preparation
then replays schema, byte hashes, semantic hashes, split assignments, B0, rank eligibility,
selected rows, full Qwen identity, CUDA/BF16, resources, config, and clean Git identity:

```powershell
uv run python tools/l2_tiny_overfit.py prepare --dataset-manifest <COLLECTION_OUTPUT>\dataset\manifest.json --qwen-cache "$env:USERPROFILE\.cache\stpd\qwen-l2" --output .local/evidence/l2/tiny-overfit-preparation
```

Preparation constructs no optimizer and writes no checkpoint. It prints and persists the
exact owner command, artifacts, pass/fail criteria, and retry rule, followed by:

`STOP - OWNER TRAINING REQUIRED: L2-TINY-OVERFIT`

Do not invoke the `run` subcommand without the repository owner's explicit authorization.
The bounded run is exactly the frozen config at
`configs/v0/experiments/l2-tiny-overfit.json`: 2–4 train examples, Scheme 1 linear,
Standard input, pretrained frozen Qwen, seed `20260822`, AdamW, 64 optimizer steps, and
checkpoints only at steps 0 and 64. It does not use Gold or B6 and cannot support a
scientific winner claim.

See [Scientific Experiment Protocol](SCIENTIFIC_EXPERIMENT_PROTOCOL.md) for the frozen
10-configuration/three-seed matrix, controls, Gates 0–5, and interpretation boundary.
