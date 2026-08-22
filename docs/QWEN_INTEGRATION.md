# Qwen Integration

## v0 decision

Core v0 uses:

```text
Qwen/Qwen3-0.6B-Base
```

The pretrained backbone is fully frozen. A same-architecture random-initialized frozen
control is required for the simplest Scheme 1 and S2-Simple comparisons. LoRA, full fine
tuning, quantized training, chat generation, and larger Qwen variants are deferred until the
pretraining-value gate is supported.

## Adapter boundary

Only the `stpd.qwen` adapter may depend on Hugging Face/PyTorch implementation objects.
Models consume the `QwenBackend` protocol from `stpd.contracts`.

Required backend operations:

- joint state-action pooled encoding for Scheme 1;
- state hidden sequence and mask for Resampler/SDT;
- frozen token embedding lookup and mask for SDT actions;
- exact model/tokenizer identity;
- deterministic device/dtype/cache configuration.

`RealQwenBackend` implements this port from an offline snapshot that must match every
checked-in file hash. It requires explicit CUDA/BF16 admission, uses eager attention,
disables generation cache, performs no silent truncation, returns detached float32
features, freezes all Qwen parameters, and exposes pretrained or seeded
same-architecture random control. `CachingQwenBackend` adds checksum-keyed CPU memory
caching without changing the scientific identity.

The backend does not choose actions, build rewards, call the environment, or own model
architecture heads.

## Identity and reproducibility

Every run records:

- model repository and immutable revision;
- tokenizer revision and special-token configuration;
- architecture/config digest;
- dtype, device, framework versions, and attention implementation;
- pretrained or random control;
- frozen parameter verification;
- cache mode and cache manifest digest.

Never rely on a moving model branch or silently updated tokenizer.

The current pin is revision
`da87bfb608c14b7cf20ba1ce41287e8de496c0cd`; `model.safetensors` is
1,192,135,096 bytes with SHA-256
`cd2a512003e2f9f3cd3c32a9c3573f820bb28c940f73c57b1ddaa983d9223eba`.
Weights remain outside Git.

## Cold and cached compute

Report separately:

- model download/setup, excluded from benchmark timing;
- cold frozen-Qwen feature extraction;
- cached feature loading;
- trainable-module compute;
- end-to-end inference per decision and per candidate action.

Scheme 1 may cache pooled joint features. S2-Simple may cache state/action/successor
vectors. S2-SDT needs the full state hidden sequence while the Resampler is trainable; a
large hidden cache is optional and its storage/read cost is part of the result.

Default S2-SDT behavior:

```text
Qwen frozen
use_cache = false
no backward graph through Qwen
micro-batched state forwards
on-the-fly resampling
```

## Input safety

- ModelState/Action serialization is deterministic and versioned.
- Runtime-local action IDs, process/session identity, hidden facts, outcomes, and teacher
  metadata are excluded.
- Prompt-like text is data serialization, not an instruction channel.
- Candidate order is not encoded through arbitrary labels or list position.

## Failure and cache invalidation

Model revision, tokenizer revision, serializer version, input profile, dtype, or Qwen config
changes invalidate derived features. Unknown cache identity fails closed instead of mixing
features from different encoders.

See [Qwen L2 Operations](QWEN_L2_OPERATIONS.md) for exact admission, smoke, preparation,
and owner-training boundaries.
