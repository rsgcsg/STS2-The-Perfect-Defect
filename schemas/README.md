# STPD Schemas

These schemas are draft v0 contracts and are intentionally conservative at cross-layer
boundaries while leaving ResearchState/Action payload details open until Step 0 is frozen.

- `research-transition-v0.schema.json`: one provenance-bound training/evaluation transition;
- `experiment-manifest-v0.schema.json`: one reproducible training or benchmark run;
- `model-artifact-manifest-v0.schema.json`: one frozen model/checkpoint artifact.

Rules:

- bump the schema identifier for incompatible changes;
- update `docs/INTERFACES.md`, tests, migration notes, and all producers/consumers together;
- never change the meaning of an existing field while retaining the same schema ID;
- validate manifests before training or evaluation;
- payload openness is not permission to add hidden state or runtime authority.
