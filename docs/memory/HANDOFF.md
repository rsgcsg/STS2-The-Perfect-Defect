# Latest Handoff

## Checkpoint

The repository has a locked Python 3.11/uv baseline and frozen first v0 contract slice while
retaining the H1 learning/transfer smoke as a qualification baseline.

The Headless/Connector lane is frozen as an exact STPD operational dependency.
Run the cheap environment smoke before training; do not repeat the full
historical qualification campaign unless an identity or hard-shell regression
occurs.

## Source baseline

Pre-initialization remote baseline:
`1b4039fe3933b408e31dd92e9fbe1454bdd7672e`.

## Added system

- canonical status, roadmap, architecture, interfaces, data, Qwen, v0, and workflow docs;
- shared Markdown memory and ADR system;
- contributor and agent rules;
- strict ResearchState/Action/Transition schemas and typed ports for environment,
  projection, serialization, Qwen, and scoring boundaries;
- deterministic profile serializers, semantic hashing, leakage rejection, stable-successor
  and execution-authority separation tests;
- canonical Parquet storage, checksummed data manifests, seed-root splits, and B0 checks;
- trainable Scheme 1/S2-Simple/S2-SDT forward paths and N/Z objective composition;
- typed optimizer steps, identity/checksum-bound checkpoint resume, and B1 ranking metrics;
- source-free Player Environment projection and stable one-step transition collection;
- B2-B7 Gold/intervention/retrieval/transfer/fixed-seed/compute report mechanics;
- structure tests that keep canonical docs and schemas discoverable.

## Next action

Attach the Headless collector and AgenticSTS importer to the frozen contracts, then exercise
source-representative local samples through the canonical Parquet/B0 path.

## Risks

- Current smoke evidence must not be confused with v0 model evidence.
- Draft interfaces may need revision when confronted with real duplicate-action and Read
  examples.
- Existing local runtime reports are not automatically evidence for this new source revision.
