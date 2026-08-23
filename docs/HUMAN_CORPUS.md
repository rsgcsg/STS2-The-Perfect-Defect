# Human Corpus Lane

This lane turns independently audited Annotator sessions into an immutable,
deterministic STPD corpus. It composes the existing strict single-session
importer; it does not reinterpret native evidence or create another legality
authority.

```text
CollectionProfile
  -> HumanSessionBundle per worker/session
  -> immutable filesystem registry
  -> strict import of every session
  -> global collision and duplicate checks
  -> whole-run + semantic-component split
  -> canonical Parquet + manifest + B0
  -> Standard token/action-size profile
  -> frozen smoke handoff
```

## Ownership

- STS2 owns gameplay truth.
- Connector owns Player Environment and BoundAction authority.
- Annotator owns native-human witness and raw session evidence.
- STPD owns registration, admission, corpus identity, split, B0, profiling and
  training eligibility.

Storage is replaceable. A local directory, NAS, Drive sync or S3-compatible
object store may carry immutable bundle directories, but storage never defines
corpus semantics. The current adapter accepts bundle-relative filesystem paths.

## Exact Collection Envelope

`collection-profiles/human-mac-combat-v1.json` pins exact game, Connector,
Annotator, protocol, Modset, platform, record schema and admitted action
families. `collection-campaigns/human-combat-smoke-2026-08.json` pins the target
record count and pseudonymous worker IDs. Profile or environment drift fails
closed; it never silently starts a new population.

Windows collection is a separate population. The exact loaded Windows x64
envelope is pinned by `collection-profiles/human-windows-combat-v1.json`, and
`collection-campaigns/human-windows-combat-smoke-2026-08.json` uses independent
worker IDs and the same 1,500-record target. Windows records must never be
packed against the macOS profile or campaign.

## Commands

Pack a closed, audited native-human session directly into the local collection:

```bash
cd ../STS2-human-Annotator
npm run pack-session -- .local/recordings/<session> \
  --profile ../STPD/collection-profiles/human-mac-combat-v1.json \
  --worker human-001 \
  --campaign human-combat-smoke-2026-08 \
  --output ../STPD/.local/human-data/sessions/human-001/<session> \
  --attest-human-origin
```

Register and build from STPD:

```bash
uv run python tools/import_human_corpus.py register \
  --profile collection-profiles/human-mac-combat-v1.json \
  --campaign collection-campaigns/human-combat-smoke-2026-08.json \
  --collection-root .local/human-data \
  --bundle .local/human-data/sessions/human-001/<session> \
  --registry .local/human-data/registry

uv run python tools/import_human_corpus.py build \
  --profile collection-profiles/human-mac-combat-v1.json \
  --campaign collection-campaigns/human-combat-smoke-2026-08.json \
  --collection-root .local/human-data \
  --registry .local/human-data/registry \
  --output-root .local/human-corpora \
  --split-salt human-combat-smoke-v1 \
  --tokenizer-file <exact-tokenizer.json> \
  --tokenizer-revision <exact-revision>

uv run python tools/import_human_corpus.py inspect \
  .local/human-corpora/human-mac-combat-v1/snapshots/<corpus>
```

The build is input-order independent. An exact retry reuses byte-identical
output; changed inputs produce a new corpus ID and cannot mutate old snapshots.

Only after the campaign minimum is met may a smoke handoff be frozen:

```bash
uv run python tools/import_human_corpus.py freeze-smoke-handoff \
  .local/human-corpora/human-mac-combat-v1/snapshots/<corpus> \
  --output-root .local/human-smoke-handoffs \
  --minimum-records 1000
```

The handoff binds corpus, Parquet, manifest, source registry, splits, B0, token
profile, serializer and exact STPD source. It explicitly sets
`training_authorized: false`; training remains a separate owner decision.
The effective threshold is the larger of `--minimum-records` and the campaign's
`target_accepted_records`; a caller cannot lower the committed campaign gate.

## Fail-closed Rules

Reject checksum or profile drift, failed/missing human attestation, invalid
single-session admission, duplicate session/bundle/export, global record or
transition collisions, a run split across roots, cross-split semantic
duplicates, B0 failure, token profile failure, or a changed immutable output.
Never edit raw evidence to pass admission.
