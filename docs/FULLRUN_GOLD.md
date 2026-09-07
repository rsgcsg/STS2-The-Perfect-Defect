# Full-Run Gold and E0-E7 Engineering Harness

This document describes the bounded engineering lane added for Full-Run Gold preparation.
It is a contract and configuration aid; it is not Human evidence, a scientific result, or a
live-game qualification.

## Gold task and label boundaries

`stpd.fullrun.gold.sample_gold_tasks` consumes an admitted `AdmittedDataset` and the existing
`FullRunSerializer`. It selects only rank-eligible `ResearchTransitionV1` records with a
complete candidate catalog, preserves the complete candidate keys and action texts, and
randomizes the recorded display order deterministically from a campaign seed. Surface quotas
are exact minimum requests. Without quotas, selection round-robins available surfaces so a
large surface cannot consume the entire task set.

Task creation does not copy `chosen_key` into a label. A task is a label-free presentation
object. The observed transition choice remains part of the admitted source contract and is
never a Gold annotation.

An annotation has one of three explicit dispositions:

- `accepted`: one or more acceptable candidate keys, an optional uniquely preferred key, and
  a finite confidence in `[0, 1]`;
- `invalid`: the task or presentation cannot be used and carries no label;
- `insufficient_information`: the annotator cannot determine an acceptable action and carries
  no label.

The candidate catalog is always complete. Multiple acceptable actions are valid, including an
accepted annotation with no uniquely preferred action. Agreement reports exact preferred-key
agreement only when both annotators provide one, and reports acceptable-set Jaccard overlap
for accepted pairs. Invalid and insufficient-information decisions remain visible in coverage
and surface disposition counts; they are never imputed as labels.

`GoldAnnotation.origin` defaults to `human`. `synthetic_fixture` is rejected by default and
can be audited only with the explicit `allow_synthetic=True` engineering-test override. The
override is not a production admission path and does not turn synthetic evidence into Human
Gold.

## Gold-dev, sealed Gold-test, and campaign isolation

`GoldCampaign.from_dataset` creates separate `gold_dev` and `gold_test` task sets. It selects
whole-run disjoint pools when the initial deterministic samples overlap, and fails closed if
the admitted source cannot provide two independent pools. A campaign identity binds the exact
source dataset logical identity, serializer, seed, and task identities.

Gold-test requires an explicit sealed audit. Access rules are enforced by
`assert_gold_access`:

- neither Gold-dev nor Gold-test may enter training;
- Gold-dev may be used for a declared tuning/evaluation step;
- sealed Gold-test may be used only by the explicit evaluation step.

No function in this lane constructs a training input, optimizer label, Human record, or live
action. The existing worker and offline evaluation contracts remain the owners of training
input and model evaluation identities.

## E0-E7 engineering harness

`default_harness_config()` returns a strict, machine-checkable engineering matrix:

| Stage | Engineering contract |
|---|---|
| E0 | Admit `ResearchTransitionV1`, complete catalogs, and causal successor or terminal evidence. |
| E1 | Compare frozen pretrained and frozen random controls. |
| E2 | Exercise the shared Linear and MLP heads. |
| E3 | Run uniform-legal and action-only baselines plus leakage checks. |
| E4 | Use one shared Full-Run model-view/candidate path across surfaces. |
| E5 | Exercise Lite, Standard, and Full provisional serializer profiles. |
| E6 | Defer multi-step dynamics. |
| E7 | Defer sealed offline promotion and live evaluation; keep Gold-test inaccessible. |

Validation rejects reordered or missing stages, weakened admission, unfrozen controls,
missing baselines/leakage checks, alternate serializer matrices, enabled dynamics, enabled
sealed/live stages, or scientific-claim flags. A valid config means that the engineering
matrix is structurally safe to run. It does not establish real-corpus coverage, Human Gold,
pretrained advantage, model quality, cloud qualification, or live capability.

Synthetic fixtures remain appropriate for portable tests of sampling, candidate permutation,
dispositions, isolation, and configuration failure. They must be identified as synthetic in
test code and never relabelled as Human Gold.
