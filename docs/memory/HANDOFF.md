# Latest Handoff

## Checkpoint

The repository has been initialized as a full STPD research project while retaining the
existing H1 learning/transfer smoke as a useful qualification baseline.

## Source baseline

Pre-initialization remote baseline:
`1b4039fe3933b408e31dd92e9fbe1454bdd7672e`.

## Added system

- canonical status, roadmap, architecture, interfaces, data, Qwen, v0, and workflow docs;
- shared Markdown memory and ADR system;
- contributor and agent rules;
- draft JSON schemas and typed Python ports for environment, projection, serialization,
  Qwen, and scoring boundaries;
- structure tests that keep canonical docs and schemas discoverable.

## Next action

Review the draft contracts against several real combat transitions, then freeze
ResearchState, ResearchAction, ModelState profiles, and ResearchTransition before collecting
or converting a large dataset.

## Risks

- Current smoke evidence must not be confused with v0 model evidence.
- Draft interfaces may need revision when confronted with real duplicate-action and Read
  examples.
- Existing local runtime reports are not automatically evidence for this new source revision.
