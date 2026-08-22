# Latest Handoff

## Checkpoint

The repository has completed the Windows L2 engineering implementation: exact full-weight
Qwen pin/acquisition/inspection, frozen pretrained and same-architecture random backends,
cache, real-Qwen smokes, contracts, data, collector/importer, three model families,
training/checkpoint/evaluation, and B0-B7 mechanics are implemented.

The first owner-authorized bounded real-data optimizer run has also occurred. Original
`L2-TINY-OVERFIT attempt-001` used the 64-step v0 engineering budget and failed only the
unchanged final-NLL and relative-loss-reduction thresholds while reaching 100% memorized
Top-1 and continuing to reduce loss through step 64. Protocol r1 therefore prepares a
strict 256-step `attempt-002` retry with no other experiment-variable change.

The Headless/Connector lane remains an exact STPD operational dependency and separate
qualification concern. Do not repeat broad historical qualification unless an identity or
hard-shell regression requires it.

## Source lineage

Windows L2 parent baseline before the full-weight implementation:
`2b918c3f5d3108b4b49cfc030588eb5cc0724bbe`.

First owner attempt source:
`a95ab022b8d81e6e697e8784893ece9c5eb1f59d`.

First owner preparation SHA-256:
`7da5ad0bf8df8c422f2affeaf6a89fb041231aac2a0d59709228c6311253302e`.

## Current experiment interpretation

Owner-reported attempt-001:

```text
initial mean listwise NLL      1.7887210548
final mean listwise NLL        0.9022365957
relative loss reduction        49.5596816%
memorized Top-1                25% -> 100%
finite values                  pass
Qwen gradients                 absent/pass
status                         fail
```

The final trace remained smoothly descending. This is evidence that the first fixed
64-step memorization budget was too short for its own strong confidence thresholds; it is
not a scientific architecture result and does not satisfy Gate 1.

## Current r1 retry

Protocol: `stpd-v0-l2-2026-08-22-r1`.

The retry keeps fixed:

```text
same rank-eligible fixture-selection rule
same pretrained frozen Qwen
same Scheme 1 linear head
same Standard input
same seed 20260822
same AdamW
same learning rate 0.001
same weight decay 0.0
same grad clip 1.0
same pass thresholds
same Gold/B6 prohibitions
```

Only the bounded optimizer budget changes:

```text
64 -> 256 optimizer steps
attempt-001 -> attempt-002
checkpoint 0/64 -> 0/256
```

The failed attempt-001 local artifacts must remain retained.

## Next action

On the Windows owner machine:

1. pull current `origin/main` with a clean worktree;
2. reuse only the old preparation's dataset-manifest path and Qwen-cache path;
3. create a new r1 preparation output directory;
4. verify the new preparation says protocol r1, 256 steps, `attempt-002`, and final checkpoint
   `checkpoint-step-256.pt`;
5. stop for owner authorization;
6. execute only the exact `owner_command` persisted by the new preparation;
7. return `result.json`, checks and trace summary for audit before any further training.

## Risks and non-claims

- Attempt-001 and any r1 retry are memorization/optimizer plumbing evidence only.
- They do not prove pretrained > random, Scheme 1 viability, policy quality, Gold quality or
  closed-loop combat performance.
- The four selected attempt-001 rows each had six candidates and target index 5. This remains
  a fixture-selection diagnostic to audit with candidate-permutation/leakage controls, not a
  proven defect.
- FakeQwen does not prove real Qwen representations.
- `card_selection` and `card_choice` token groups remain naturally unexercised.
- No Core 30-run scientific matrix, Human Gold result, B6 result or v0 winner exists.
