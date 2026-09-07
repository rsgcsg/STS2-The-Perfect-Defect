# STPD Development Workflow

## Ownership and branches

STS2 AI Platform is the model-neutral environment foundation. STPD is an independently
versioned research consumer, not a second platform. Public exact contracts connect them;
there is no shared branch or submodule relationship. STPD never owns native rules, legality,
execution, Receipt or successor truth. Platform never imports STPD model/reward semantics.

main at 4c4bbca5e5bf16656bd7c0ba175ff5c069c81818 remains the historical
baseline/pre-governance-stpd-20260827, not a stable research-release claim. develop is the
single normal integration line. Governed releases follow develop -> release/<version> ->
main -> version tag. Synchronize stabilization fixes back to develop.

Use short-lived contract/environment/data/representation/model/training/evaluation/
qualification/policy/docs/ops/experiment topic branches. release/* stabilizes a release;
hotfix/* starts at main for urgent fixes and returns to develop. No permanent model/component
integration branches. Prefer one causal responsibility per PR; separate structural changes
from scientific experiments. Topic PRs normally squash.

## Preflight and concurrency

Fetch/prune, resolve exact develop, inspect open PRs and current rules, then create one
branch/worktree per writer. A restricted connector session must say when it has not obtained
a local checkout. Exact API reads do not prove local execution. Never overwrite another
writer's new commit. Re-resolve the parent before a write; use fast-forward-only topic updates.

Stack only with explicit prerequisites and exact parent identities. Preserve work remotely;
a missing merge permission is not a reason to abandon independent implementation. Retarget
or merge in dependency order only under the task's authorization and current governance.
No force update, protected direct push, or routine admin bypass.

## One supported environment and gate

```bash
uv sync --locked --all-extras
npm ci
uv run --locked python tools/project.py context
uv run --locked python tools/project.py check
uv run --locked python tools/project.py closeout --base <exact-base-sha>
```

Python >=3.11,<3.12 and uv.lock are machine authority. Cold dependency provisioning can need
network; source tests need no game, Human data, weights, GPU or production credentials.
Both Linux and Windows run the same root gate. See [Testing](TESTING.md).

PRs record exact base/head, owning fact, change class, failure model, affected consumers,
Platform pin, data/model/protocol/service impact, real tests, review, rollback and non-claims.
A new head requires new evidence. Squash does not transfer source-bound runtime or scientific
evidence; re-verify the resulting identity when that evidence is required.

## Exact dependencies and evidence

Consume immutable public Platform releases or explicitly non-stable candidates bound to
source, artifact/package digest and protocol. No floating develop dependency, sibling-source
import, or unversioned local artifact. Cross-repository changes use separate PRs and exact
consumer admission. Platform lifecycle defects are repaired at Platform, not hidden in STPD.

Keep raw/private data, game files, weights, caches, credentials and large artifacts outside
Git. Record manifests, hashes, commands and reviewed reports. Failed runs remain failed.
Source/test, data, training, model-quality, service and scientific evidence are independent.

## Merge and release

Inspect the live ruleset rather than inferring protection from this document. The current
policy requires PRs, locked-python, resolved review conversations, no force update/deletion
and no bypass on governed branches. Respect any stronger live rule. Merge only the exact
reviewed/latest-head candidate after every required check and review condition is satisfied.

Release branches admit stabilization, versioning, provenance and reports, not new scientific
experiments. A release/version label never proves model quality or runtime qualification.
See [Engineering Governance](ENGINEERING_GOVERNANCE.md) and [Project System](PROJECT_SYSTEM.md).
