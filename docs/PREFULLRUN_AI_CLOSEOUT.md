# Pre-Full-Run AI engineering closeout

This phase delivers the Local-First engineering system. The terminal engineering verdict is
`STPD_PRE_FULLRUN_AI_ENGINEERING_READY` only when the exact current source has the reviewed
qualification receipt described below. This document does not substitute an ancestor CI pass
for a current-head result.

## Exact final refs and evidence

The final task PR is [#7](https://github.com/rsgcsg/STS2-The-Perfect-Defect/pull/7), targeting
`develop`, based on `ae4c8ac43caf224b01951c030842a60814a09bea`. Its final head and merge SHA,
latest integrated develop SHA, hosted Linux/Windows/locked-python jobs, full portable output,
clean-checkout CPU E2E and readiness result are recorded in the exact-source Git note:

```bash
git fetch origin develop refs/notes/stpd-prefullrun:refs/notes/stpd-prefullrun
git rev-parse origin/develop
git notes --ref=stpd-prefullrun show origin/develop
```

The note contains the literal final source/develop SHA and CI run URL. Keeping the receipt
outside the source tree avoids changing a commit's identity by inserting that commit's own
SHA into it. Each note is bound to one exact commit, and is pushed only after its checks
pass. An absent note or mismatching source is not final evidence. No source/check result is
inherited after another edit; rerun `tools/qualify_prefullrun.py --ci-run <exact-run>`.

## Converged topology

The convergence line preserves the source and historical evidence of #2–#6, including the
newer lifecycle and storage race repairs that diverged from their children. The original
five task PRs are superseded by #7 only after that replacement is durable and integrated.
Exact original heads are retained in Git history:

| PR | Original head | Disposition |
|---|---|---|
| #2 | `393791804b5e398d81e4d8fa67d9f9f8d9a15e76` | lifecycle implementation and repair preserved |
| #3 | `7f1c77ed724aca3dee0ebecfb780197e80b9dc85` | governance/portable gate preserved |
| #4 | `267a07544ffdfa13c0753962c924ca2d91e8b416` | storage and newer race tests preserved |
| #5 | `38d32dbf440b5121c3bfd915f6d8cbf22b1dfc63` | separately versioned Full-Run research preserved |
| #6 | `dcda0798dc2ab7bb160514299e159d9e6034fa5b` | worker/training/evaluation preserved and hardened |

`ops/prefullrun/research-workbench-v1` originally equalled #6; no unique work was discarded.
`ops/prefullrun/finish-v2` at `122a56ea215c83a1f9c0ac4b06eb7c3a323de946` added only source/tools
snapshot workflows relative to #6. Those transport-only workflows are excluded from the
product. Historical branches/evidence remain recoverable; no protected history was rewritten.
The final note and PR contain actual merged/closed dispositions, rather than a predicted merge.

## Final architecture and repairs

Platform remains the sole owner of semantic S, complete A_sem(S), Human/native correlation,
Commit and causal successor. The installed source adapter is explicitly synthetic. The final
qualified Platform format is not guessed. In-memory scope flags cannot create qualification.

STPD owns `ResearchTransitionV1`, admission/dedup, whole-run semantic-component splits,
provisional Lite/Standard/Full ModelView, frozen FeatureSet, exact TrainingInput,
Experiment/Run, one shared Linear/MLP scorer, Checkpoint/Model and OfflineEvaluation. Historical
combat-v0/H1/S1 remain reproducible under their original evidence boundaries.

Local/S3-compatible ArtifactStore owns canonical immutable manifests and content-addressed
payloads, published manifest-last with hash/size verification and no-overwrite semantics.
SQLite Registry is rebuildable; DuckDB and escaped local HTML are projections. RunReporter
owns conditional result selection and immutable attempt events. Future Hub adapters need not
change scientific IDs. Workers are disposable and provider-neutral; there is no permanent
server, cloud STS2, scene-specific model head or provider-specific training core.

Substantive repairs address causal boundaries: unique parent roles, exact source/lock and
executing-checkout binding, credential-bearing durable fields, lexical/reparse-safe publication,
float32 overflow and bounded NPY header validation, provenance re-verification, stricter
leakage rejection, complete evaluation row inventory/summary/model-view lineage, checkpoint /
model / evaluation validation on idempotent completion, and conditional publication races.
Gold-dev/test inherit existing dev/test splits; task identities bind presentation and source,
annotations bind state/catalog/display order, distinct annotators determine agreement, and
synthetic tasks cannot manufacture Human Gold. Sealed collection exposes coverage, never
silently tuning metrics. Analysis uses canonical loaders and separates actual dataset counts
from repeated evaluation rows; comparisons bind model/config/Qwen/profile/dataset IDs.

## Verification contract

Both hosted portable jobs execute locked Python 3.11 bootstrap, exact npm packages, doctor,
Ruff, Mypy, Connector SDK tests, full Pytest, CPU E2E, compileall, package build and patch
hygiene. `locked-python` rejects either failed/skipped/cancelled lane. A changing checkout
invalidates local closeout. Exact test counts and CI URLs live in the final-source note.

The clean CPU E2E exercises synthetic multi-surface source → admission and actual dedup →
whole-run split → Dataset → ModelView → FakeQwen FeatureSet → TrainingInput → Linear and MLP
training → durable checkpoint → transfer to a fresh store → new-process resume → Model and
offline baselines → duplicate completion → Registry deletion/rebuild → sync → DuckDB →
dashboard/lineage → sealed synthetic Gold coverage → E0–E7 config → read-only readiness.

Adversarial review covered artifact publication/identity, Dataset/splits, feature inputs,
completion/checkpoint/model/evaluation lineage, secret-shaped metadata and portability.
Worker summaries were inspected and their actual code/tests integrated; unfinished review
work was completed by the lead. Source/tests and latest hosted checks are the acceptance facts.

## Remaining gates and non-claims

Only final qualified Platform bundle/schema, real storage/GPU provisioning/account smoke,
real Human Gold and real STS2 live/scientific operation remain outside this engineering scope.
See [Human handoff](PREFULLRUN_HUMAN_HANDOFF.md) and [operations](PREFULLRUN_OPERATIONS.md).
No real Full-Run Dataset, Human Gold, S3 deployment qualification, GPU-provider qualification,
pretrained-Qwen advantage, model quality, completed scientific campaign or live-STPD result
is claimed. Synthetic performance fixtures and whitespace token proxies are not real GPU or
Qwen measurements. Final Standard freezes only after real-corpus profiling.
