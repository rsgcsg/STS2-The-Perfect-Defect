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

## D-006 — Consume the exact Headless v1.0 operational baseline

**Status:** accepted

STPD pins Headless `v1.0.0`, its exact Managed Host tuple and Connector
`v1.1.0-rc.1` protocol `1.0.0` as the current environment dependency.
Formal H1.0 and exhaustive qualification are not implied. Identity change or
an environment-invalid episode reopens only the affected gates; routine
training starts with the cheap fail-closed environment smoke.

## D-007 — Advance the operational patch without transferring evidence

**Status:** accepted; supersedes D-006 for current execution

STPD consumes Headless `v1.0.1` and its exact `8ced088b...` patch / `8dc622b0...`
Host while retaining Connector `v1.1.0-rc.1` and protocol/SDK `1.0.0`. The different
Headless `v1.0.0` Host remains immutable predecessor evidence; runtime authority does not
transfer across the artifact change.

## D-008 — Version Standard Human serialization without rewriting history

**Status:** accepted

Keep serializer v0 and every historical profile/corpus frozen. Serializer v1
removes only the redundant Standard combat `facts.referents` rendering after
strict evidence projection; Full/Lite, records, actions and successors remain
unchanged. Cross-platform training data is combined only through the exact
profile digests in `human-combat-unified-v2`, then globally re-split and gated.

See [ADR-0002](../adr/0002-versioned-unified-human-serialization.md).

## D-009 — Keep live S1 authority in Connector and handoff whole catalogs

**Status:** accepted for experimental live v1

The trained STPD policy may score only the exact current Connector catalog after
research projection. It never reconstructs legality, filters unsupported
candidates, or sends native input. Human is the default owner; a controller lease
exists only for admitted Qwen execution and is released on handoff. Stale means
fresh observation without request retry; unknown delivery permanently stops
automation for that runner process. Live evidence is local and explicitly
non-scientific.

## D-010 — Match live Read selection to the trained Human representation

**Status:** accepted for experimental live v1

Keep Connector's `reads[]` as a multi-instance array identified by opaque
`read_id`; duplicate kinds are not collisions. The completed Human checkpoint
was trained on importer-projected `reads={}`, so its live config prefetches no
Read responses and passes the same empty mapping to `ResearchProjectorV0`.
Advertised descriptors remain in the authoritative Snapshot and evidence. A
future model that trains on Reads requires a new explicit deterministic
multi-instance projection and compatibility evidence rather than changing this
checkpoint's input semantics. Legacy collectors that request a kind-keyed Read
mapping fail closed when a requested kind is not unique instead of overwriting.
