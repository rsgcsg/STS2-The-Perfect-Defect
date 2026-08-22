# Qwen L1 Metadata and Tokenizer Handoff

This slice validates the frozen Qwen identity and input-token budget without downloading
or loading model weights. It is an L1 metadata/tokenizer gate, not Qwen representation,
training, or model-quality evidence.

## Pinned identity

The checked-in pin is
`configs/v0/qwen/qwen3-0.6b-base-l1.json`:

```text
model:    Qwen/Qwen3-0.6B-Base
revision: da87bfb608c14b7cf20ba1ce41287e8de496c0cd
```

The pin records the SHA-256 and byte size of `config.json`,
`generation_config.json`, `tokenizer_config.json`, `tokenizer.json`, `vocab.json`,
and `merges.txt`, plus explicit config SHA, tokenizer-bundle SHA, and the ordered
special-token ID/role digest. The remote revision
also advertises `model.safetensors`; that file is explicitly excluded and is never
requested by the fetch command.

## Explicit online operation

The only command that may access the Hub is `fetch`. It downloads the six allow-listed
files into a deterministic cache and writes a manifest outside the snapshot:

```bash
uv run python tools/qwen_l1.py discover --pin configs/v0/qwen/qwen3-0.6b-base-l1.json
uv run python tools/qwen_l1.py fetch \
  --cache-dir "$HOME/.cache/stpd/qwen-l1" \
  --pin configs/v0/qwen/qwen3-0.6b-base-l1.json \
  --output /tmp/stpd-qwen-l1-fetch.json
```

`fetch` fails closed on a missing allow-listed file, content mismatch, unexpected local
file, or any local weight file. Remote weight names are reported as rejected remote
files; they are not downloaded. Authentication is read only from `HF_TOKEN` by the
tool and is never written to an artifact.

The observed online evidence for this pin was:

```text
remote revision: da87bfb608c14b7cf20ba1ce41287e8de496c0cd
allow-listed payload: 11,490,874 bytes
model.safetensors requested: no
local weight after fetch experiment: no
```

## Offline inspection and profiling

These commands do not access the network:

```bash
uv run python tools/qwen_l1.py inspect \
  --cache-dir "$HOME/.cache/stpd/qwen-l1" \
  --pin configs/v0/qwen/qwen3-0.6b-base-l1.json

uv run python tools/qwen_l1.py profile \
  --cache-dir "$HOME/.cache/stpd/qwen-l1" \
  --input /path/to/profile.jsonl \
  --output /tmp/stpd-qwen-token-profile.json
```

Each JSONL record has exactly the profile/family labels and text to tokenize:

```json
{"profile":"stpd-combat-v0-standard","family":"turn_action","text":"..."}
```

The report is stratified by the three profiles and `turn_action`, `card_selection`,
and `card_choice`, and includes P50/P90/P95/P99/max. Quantiles use deterministic
nearest-rank semantics. No truncation is enabled. Any max above 8192 or P95 above
4096 makes the report fail; missing profile/family groups are `not_exercised` and do
not become a pass through aggregation.

For offline tests, pass `--tokenizer-file` with a deliberately supplied fixture tokenizer.
That proves the profiling and fail-closed behavior only; it is not evidence about the
Qwen tokenizer until the pinned cache has been fetched and inspected.

## Deterministic fake backend

`stpd.qwen.fake_backend.DeterministicFakeQwenBackend` implements the existing
`contracts.QwenBackend` port for shape and pipeline tests. It returns deterministic CPU
tensors, padded boolean masks, and a stable fake identity without loading a tokenizer or
any model file. `encode_joint` returns pooled `[batch, hidden]`; sequence state and action
methods return `(hidden, mask)` with `[batch, tokens, hidden]` and `[batch, tokens]`, while
pooled `encode_state(..., return_sequence=False)` preserves the current consumer port.

This backend is deliberately **not** a random-initialized Qwen scientific control. Its
outputs have no representation-quality, pretraining-value, or model-comparison meaning.
It may prove tensor shapes, padding masks, deterministic cache keys, and model wiring only.
Scientific controls require a separately implemented and explicitly identified experiment;
this L1 slice neither downloads weights nor makes that claim.

## Evidence boundary

This handoff proves only source/config implementation, deterministic offline tests, and
the explicitly recorded metadata/tokenizer fetch evidence. It does not prove model
weights, frozen parameters, Qwen hidden representations, GPU behavior, training quality,
or a completed STPD B0/B1 gate. A real profile report must be generated from the pinned
`tokenizer.json` and retained outside Git as run evidence.
