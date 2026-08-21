# Accepted Decisions

Append new decisions; do not rewrite history except for typo or link corrections.

## D-001 — Preserve the current smoke lane

**Status:** accepted

The linear-Q, learning, contention, and Reference-transfer code is classified as H1
integration/qualification infrastructure. It is not the final v0 model, but it remains useful
and will not be deleted or moved without a tested compatibility migration.

See [ADR-0001](../adr/0001-project-boundaries-and-current-smoke.md).

## D-002 — Keep environment authority outside STPD

**Status:** accepted

STS2/Host owns game transitions and Connector owns Player Environment semantics. STPD may
project, serialize, score, learn, and evaluate, but may not reconstruct legality or execute
native operands.

## D-003 — Frozen Qwen core experiment

**Status:** accepted for v0 core

Use pinned `Qwen/Qwen3-0.6B-Base`, fully frozen, with a same-architecture random frozen
control. LoRA/full fine-tuning is deferred until pretraining value is demonstrated.

## D-004 — Standard input for architecture selection

**Status:** accepted for v0 core

Run all 10 core configurations with `stpd-combat-v0-standard`. Run Lite/Full only for the
frozen Scheme 1 and Scheme 2 winners.

## D-005 — Separate eligibility types

**Status:** accepted

Data records keep `rank`, `transition`, and `return` eligibility separate. Teacher choice is
behavior supervision, not optimal-Q truth; exploratory actions may train dynamics without
training imitation.
