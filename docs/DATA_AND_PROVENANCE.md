# Data and Provenance

## Data flow

```text
external/local source
-> immutable raw zone
-> validated Player Environment records
-> ResearchState/Action/Transition normalization
-> eligibility and policy provenance
-> episode/run/seed-root split manifests
-> optional frozen-Qwen features
-> training/evaluation datasets
```

Only manifests, schemas, checksums, reviewed summaries, and small synthetic fixtures belong
in Git. Raw traces, saves, model caches, and external datasets stay local or in an approved
artifact store.

The implemented `stpd.data` pipeline reads explicit raw JSONL without correction/defaults,
validates the frozen transition schemas and B0 invariants, assigns whole seed roots to a
deterministic split, then writes canonical-JSON Arrow columns to compressed Parquet. Nested
JSON is the contract; Arrow is storage, not a second semantic authority.

## Data zones

- `data/raw/`: immutable source capture; ignored.
- `data/external/`: licensed/public external material; ignored.
- `data/normalized/`: versioned ResearchTransition records; ignored.
- `data/features/`: Qwen or other derived features; ignored and cacheable.
- `data/manifests/`: tracked dataset/split/provenance manifests.
- `data/gold/`: only reviewed manifests and redistributable annotations; raw private notes
  remain external.

## Required provenance

Every transition records:

- policy source/version and optional confidence;
- rank/transition/return eligibility;
- episode ID, seed, game version;
- exact Host and Connector identities;
- input profile and schema versions;
- legal actions, chosen action, stable successor, terminal/outcome status.

Multi-source data remains queryable by source. Do not collapse strong teacher, heuristic,
random exploration, historical agent, current model, or human data into an anonymous pool.

## Splits and leakage

Split by episode/run/seed root, never by adjacent turn. Requirements:

- normalized state hashes do not cross train/validation/test;
- Gold-dev and Gold-test are separate manifests;
- Gold-test remains sealed until architecture/input/hyperparameters are frozen;
- future outcome, teacher identity, runtime IDs, hidden state, and test labels are absent from
  model inputs;
- candidate action order is randomized or recorded;
- duplicate and near-duplicate states are measured, not ignored.

B0 failure invalidates the experiment.

The current executable B0 checks schema validity, unique transition/action identity, chosen
action membership, fair-player model-input leakage, complete listwise catalogs, stable
successor semantics, inadmissible lifecycle reason codes, manifest row counts, and semantic
duplicates crossing splits. Large-corpus approximate-neighbor analysis remains pending and
must be added before large external data admission.

## Eligibility

- `rank_eligible`: action choice is suitable behavior supervision.
- `transition_eligible`: state/action/stable-successor semantics are reliable.
- `return_eligible`: terminal outcome and trajectory linkage are reliable.

A weak or random action can be valuable transition data while remaining rank-ineligible.
Observed returns estimate behavior-policy value, not optimal Q.

## External data risks

External processing must address:

- game/Connector/Host version drift;
- stale or incomplete legal action catalogs;
- unstable or transient successor capture;
- localization and text normalization;
- policy-source bias and source imbalance;
- licensing, redistribution, privacy, and service terms;
- hidden information and future-label leakage;
- duplicate episodes and train/test contamination;
- missing negative/counterfactual actions;
- changes in serializer, tokenizer, model revision, or cache format.

Unknown rights or provenance means exclude the source from training.

## Sampling

Rank batches draw primarily from rank-eligible sources and should be source-balanced.
Dynamics batches may draw from all transition-eligible sources. Candidate actions for one
state stay grouped for ranking loss; do not turn them into unrelated BCE examples.
