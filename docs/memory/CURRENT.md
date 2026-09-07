# Current Context

The Pre-Full-Run Local-First system converges through PR #7 onto develop. Read
PREFULLRUN_AI_CLOSEOUT and PREFULLRUN_HUMAN_HANDOFF. Exact final source/develop SHAs, PR
classification, portable jobs, clean CPU E2E and readiness receipt are bound to the final
commit by the pushed refs/notes/stpd-prefullrun Git note. Re-resolve remote refs and verify
that receipt; a missing or stale note is not a pass.

Architecture: separately versioned ResearchTransitionV1; thin synthetic adapter until final
Platform bytes; whole-run/component admission and splits; provisional ModelView; frozen
FeatureSet/TrainingInput; shared Linear/MLP scorer; disposable worker/checkpoint/resume;
immutable ArtifactStore/RunReporter; rebuildable Registry; DuckDB/static local dashboard;
Gold collection/sealed isolation and E0-E7 engineering configuration.

Platform owns S/A_sem/Commit/causal successor/Human correlation. Preserve H != S and
A_public != A_sem(S). Remaining external gates: final Platform bundle/schema, real object-store
and GPU accounts, Human Gold and real STS2/scientific execution. No scientific promotion from
engineering evidence; historical combat-v0/H1/S1 retain their original scope.

Use tools/project.py check/closeout and tools/qualify_prefullrun.py --ci-run <exact-run>.
No permanent server or provider-specific training code is required.
