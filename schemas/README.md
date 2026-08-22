# STPD Schemas

The research state/action/transition schemas are the frozen structural v0 contracts. Their
fair-player semantic payloads remain extensible inside `facts` and `reads`; top-level meaning
is closed and versioned.

- `research-state-v0.schema.json`: one coherent fair-player semantic decision state;
- `research-action-v0.schema.json`: one legal candidate's visible semantic meaning;
- `research-transition-v0.schema.json`: one provenance-bound stable-successor transition;
- `data-manifest-v0.schema.json`: checksummed source, split, deduplication, and file lineage;
- `experiment-manifest-v0.schema.json`: one reproducible training or benchmark run;
- `model-artifact-manifest-v0.schema.json`: one frozen model/checkpoint artifact.

Rules:

- bump the schema identifier for incompatible changes;
- update `docs/INTERFACES.md`, tests, migration notes, and all producers/consumers together;
- never change the meaning of an existing field while retaining the same schema ID;
- validate manifests before training or evaluation;
- payload openness is not permission to add hidden state or runtime authority; executable
  leakage tests are the second line of defense.
