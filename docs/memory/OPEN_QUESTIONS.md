# Open Questions

## Contracts

- What exact fields belong in ResearchState v0 for combat, and which Reads are required?
- How is a deterministic `action_key` constructed for duplicate-looking but distinguishable
  actions without leaking runtime authority?
- What is the canonical normalized-state hash and text normalization policy?

## Data

- Which existing trajectories are rank-, transition-, and return-eligible?
- What redistribution/licensing constraints apply to historical and teacher data?
- How many current-patch transitions are available before model development begins?
- How will Human Gold annotation, disagreement, and test sealing be operated?

## Qwen and compute

- Which immutable Qwen/tokenizer revision will be pinned?
- What pooling definition is used for Scheme 1 and S2-Simple?
- Is on-the-fly S2-SDT encoding sufficient, or is a sharded hidden-state cache required?
- What hardware envelope defines the v0 compute budget?

## Evaluation

- What exact fixed-seed combat suite and non-combat controller are frozen for B6?
- What practical-significance threshold is meaningful for Gold/live paired differences?
- What current-patch and Reference sample counts are feasible?

Each resolved question should link to code/schema/evidence and move into an ADR or canonical
document when the answer is durable.
