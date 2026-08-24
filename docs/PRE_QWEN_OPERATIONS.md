# Pre-Qwen Operations And L2 Handoff

## Local readiness

The doctor is offline unless a caller separately runs the explicit Qwen L1 fetch. It rejects
a dirty source tree, wrong Python, malformed schemas, tracked weight files, a mismatched L1
cache, a mismatched public Host Runtime package, or a failed exact candidate audit:

```bash
uv sync --frozen --all-extras
uv run python tools/doctor.py \
  --require-qwen-cache \
  --qwen-cache "$HOME/.cache/stpd/qwen-l1" \
  --candidate /absolute/path/to/<exact-candidate> \
  --output .local/evidence/preqwen-doctor/report.json
```

`npm ci` installs the Host Runtime version pinned by
`configs/v0/platform-host-runtime-v1.json`; no sibling source checkout is consulted.
The report proves local identity/file readiness only. Candidate audit is not gameplay
qualification, and L1 contains no weights.

## Engineering smoke

```bash
uv run python tools/preqwen_smoke.py \
  --output .local/evidence/preqwen-fake-smoke
```

This runs Scheme 1, S2-Simple and S2-SDT through one FakeQwen optimizer step, atomic
checkpoint/resume and checksum-bound artifact verification. It is not a random-Qwen control,
learning result or model comparison.

## Portable L2 manifest

After a current runtime collection, create a secret-free, path-free rebuild manifest:

```bash
uv run python tools/create_l2_handoff.py \
  --qwen-cache "$HOME/.cache/stpd/qwen-l1" \
  --runtime-report .local/evidence/<collection>/report.json \
  --data-manifest .local/evidence/<collection>/dataset/manifest.json \
  --output .local/handoff/stpd-l2-handoff.json
```

The manifest pins Git, `uv.lock`, Qwen metadata/tokenizer and exact environment identities.
Full Qwen weights are explicitly `required_external_not_present_in_l1`; game files, secrets,
absolute paths and caches are never embedded. On Windows/cloud, clone the pinned revision,
run `uv sync --frozen --all-extras`, obtain the pinned weights through approved external
storage, then rerun doctor before any scientific experiment.
