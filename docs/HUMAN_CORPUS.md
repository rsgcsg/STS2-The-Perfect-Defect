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

Platform/profile corpora remain independent admission units. The final smoke
lane combines only immutable admitted snapshots; it never concatenates raw
JSONL or bypasses per-session admission:

```text
admitted macOS corpus + admitted Windows corpus + future admitted profile corpora
  -> exact compatibility check
  -> global collision/dedup + whole-run split
  -> combined Parquet + B0 + Standard profile
  -> immutable combined corpus
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

## Evidence Versions

The existing 1,962-record training corpus remains a V1 corpus and is unchanged.
V1 bundle integrity is verified by the pinned Platform Evidence package, with
the previous STPD verifier retained under test as a parity oracle.

Portable V2 bundles add CaptureProfile, RunJournal and content-addressed Read
blobs. STPD accepts them only through `import_verified_human_bundle`; direct V2
JSONL import fails closed. Verified `run_deck` and `combat_piles` Reads are
projected into state and successor without changing corpus or training
authorization. Exact native-human object `b92778bed35ab129...` verifies this
path for 30 ordinary-Combat records from runtime `abb6b2d8...`; all 30 imported
with both required Reads in state and successor. It is not part of the frozen
V1 corpus and generated-card choice remains `not exercised`.

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

A later exact Windows artifact is independently pinned by
`human-windows-combat-v2`. Historical profiles remain frozen; identity drift is
represented by a new profile/campaign rather than rewriting v1.

## Commands

Pack a closed, audited native-human session directly into the local collection:

```bash
cd ../STS2-AI-PLATFORM
npm run annotator:pack-session -- components/annotator/.local/recordings/<session> \
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
  --tokenizer-revision <exact-revision> \
  --serializer-version stpd-model-serialization-v1

uv run python tools/import_human_corpus.py inspect \
  .local/human-corpora/human-mac-combat-v1/snapshots/<corpus>
```

The build is input-order independent. An exact retry reuses byte-identical
output; changed inputs produce a new corpus ID and cannot mutate old snapshots.

## Final Cross-Profile Merge

`corpus-combinations/human-combat-unified-v2.json` is the versioned
compatibility and target policy. It admits exact profile digests while allowing
platform-specific game/Mod/Annotator artifacts. It requires the same Player
Environment protocol, Connector semantic source digest, record schema,
ResearchTransition contract, serializer, tokenizer and action-family envelope.
Unknown profiles or any incompatible field fail closed.

The v2 plan explicitly selects `stpd-model-serialization-v1`. For Standard
combat turn-action text only, v1 omits `facts.referents` because the same
player-visible referents are already present in the complete interaction and
structured combat/card facts. Full and Lite remain unchanged. No record,
candidate, state fact, action family or successor is truncated or removed.

After each machine has independently produced an immutable profile snapshot:

```bash
TOKENIZER="$HOME/.cache/stpd/qwen-l1/models--Qwen--Qwen3-0.6B-Base/snapshots/da87bfb608c14b7cf20ba1ce41287e8de496c0cd/tokenizer.json"

uv run python tools/import_human_corpus.py combine \
  --plan corpus-combinations/human-combat-unified-v2.json \
  --profile-root collection-profiles \
  --snapshot <mac-corpus-snapshot> \
  --snapshot <windows-corpus-snapshot> \
  --output-root .local/human-unified-corpora \
  --split-salt human-combat-unified-v2-split-000 \
  --tokenizer-file "$TOKENIZER" \
  --tokenizer-revision da87bfb608c14b7cf20ba1ce41287e8de496c0cd
```

The merger re-verifies every snapshot checksum, profile identity, manifest,
Parquet record hash, B0 result and tokenizer identity. It preserves nested
session/worker/profile/platform provenance, rejects transition collisions,
recomputes global semantic components/splits and reports source, platform and
action-family distributions. Reordered inputs produce the same ID; adding an
input produces a new snapshot and cannot alter old output. A combined snapshot
uses the same `inspect` and `freeze-smoke-handoff` commands as a profile corpus.

Only after the campaign minimum is met may a smoke handoff be frozen:

```bash
uv run python tools/import_human_corpus.py freeze-smoke-handoff \
  .local/human-unified-corpora/human-combat-unified-v2/snapshots/<corpus> \
  --output-root .local/human-smoke-handoffs \
  --minimum-records 1500
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

## Owner-gated S1 preparation

After the immutable unified handoff and exact-source Qwen engineering smokes
pass, `tools/s1_smoke.py prepare` writes `.local/training-ready/READY_TO_TRAIN.json`
and `.local/training-ready/START_TRAINING.ps1`. Preparation validates every
source/data/Qwen/runtime/config identity and constructs no optimizer. The start
script replays those checks and requires the exact owner acknowledgement before
the first optimizer is created. It opens neither Human Gold nor Gold-test and is
not a Core scientific run.
