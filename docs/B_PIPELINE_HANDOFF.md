# B pipeline: release, terminal handoff and next gates

This is the current cross-repository operator entry. [B operations](CLOUD_PIPELINE_B.md)
owns the data/worker mechanics; [Hub runbook](../deploy/hub/RUNBOOK.md) owns host commands.
This document defines their order and acceptance boundaries, not a claim that a deployment,
Human session or training campaign passed. Exact receipts are bound to their own source.

## One system, separate owners

| Owner | Delivers | Does not decide |
|---|---|---|
| Platform | one game Mod; fixed collection tool; Evidence package/outbox; policy lifecycle | research admission, model, training, GPU provider |
| STPD | one developer workbench; projection/Dataset; Hub; worker/provider adapter; model policy adapter | native rules, legal actions, Human/Commit/successor truth |
| Operator | exact approved combination, device access, budget, backup and deployment | rewriting failed evidence or changing a frozen experiment retrospectively |
| Model artifact | immutable weights, representation/support manifest and provenance | installing an unpinned environment or activating gameplay automatically |

Public OCI images contain public source and dependencies only. Runtime secrets, recordings,
operational databases and model weights are external. Public download grants no Hub/R2/Modal
permission. A private registry is a supported future deployment choice, requiring separate
read-only pull credentials and adapter/rotation tests; it is not a second training system.
Do not put private payloads in image layers and then delete them in a later layer.

## What is distributed now

B is a developer distribution, not a one-click player installer. Each participating terminal
needs the owned game, one qualified Platform Mod, Git, Node 20+, Python 3.11/uv and the .NET
runtime declared by the collection tool. Clone STPD at the operator-approved exact commit;
`uv sync --locked --all-extras` and `npm ci` supply pinned public dependencies. A Platform
clone is needed only by Platform developers or the release builder, not every collector.
There is one external workbench command surface; models are optional separate downloads.

The release builder produces the fixed collection-tool directory once, from a clean exact
Platform checkout, using its `publish:collection-tool` command. Distribute the entire directory,
its inventory and its independently pinned release ID. This command creates a local release;
it does **not** upload GitHub assets or prove any native Mod was installed. An adjacent manifest
alone is not trust. The operator records the approved release ID outside the downloaded files.

A reviewable terminal handoff contains:

- exact Platform workspace/component/BOM and installed Mod identity; exact collection-tool
  inventory/release ID and required .NET runtime; never the game binaries;
- exact STPD commit/lock and developer combination, public Evidence dependency pin;
- public Hub URL and explicit HTTPS upload-host allowlist;
- private device token delivered separately from a non-secret configuration example;
- private campaign config, dedicated recording and outbox paths, startup/stop/status commands,
  and the campaign's explicit Human-origin attestation scope;
- supported OS and tested gate, known limitations, rollback and incident instructions.

Do not distribute a developer's `.local`, `.env`, home directory, SQLite or outbox. Never give
collectors R2 access keys, the Hub admin token, registry publish credentials or Modal credentials.
A copied public handoff is a template; it cannot grant consent on behalf of another operator.

## First terminal and real-upload gate

1. Complete source review/root gates/latest-head CI in each repository. Prepare the exact Mod
   and tool artifacts; an unmerged candidate is explicitly non-stable. Update the STPD pin only
   after the Platform candidate is durable and reviewed. Requalify the final Hub image at its
   new source/lock; old cloud receipts remain historical. No merge transfers runtime evidence.
2. Separate qualification from collection: preserve the synthetic Hub state/prefix and prepare
   fresh collection state/prefix with budget zero, private permissions, backup/status checks and
   no configured GPU target. The public service being healthy is not a Human-upload permission.
3. Register one revocable device token and prepare its local campaign config. Use a **dedicated
   initially empty recording root** and a separate new outbox. The current delivery service
   discovers every sealed session under its configured root: do not aim it at a historical
   archive. Bind the game recording destination through Platform's supported profile/runtime
   configuration. Do not infer campaign membership from timestamps or copy/mutate sealed files.
4. Run project setup and the owning read-only delivery preflight through `project doctor`.
   Inspect source/tool/pin/.NET/config/token checks and the discovered-session count. A failed
   preflight blocks open. No automatic collection starts merely because setup ran.
5. The Human explicitly authorizes this campaign's upload and attests its origin. Start the
   exact workbench/delivery process, then the Human records a new bounded session and presses
   Recorder Close. The agent never supplies gameplay, console actions or attestation.
6. Verify the local seal, immutable outbox/archive IDs, public Hub receipt and R2 manifest/bytes.
   Repeat a client restart to recover the same receipt. Confirm failed native decisions remain
   failures, pending means pending and no historical session was unexpectedly enrolled.
7. Retain local raw evidence and the verified bundle; do not auto-delete either. Back up the
   operations DB and record exact source, loaded runtime, tool, campaign and upload identities.
   Mark only this bounded Close-to-remote gate passed. Collection at other terminals/OS versions
   needs the same preflight and a bounded first upload.

Current terminal commands are in [B operations](CLOUD_PIPELINE_B.md#developer-terminal).
`project open` supervises delivery; closing a dashboard tab does not stop it. Use `project stop`
for its owned background process. Offline sealed work reconciles when the same config reopens.
The Human can keep playing offline; upload state is not native decision validity.

## Daily work, upgrades and incidents

| Event | Required workflow | Retained evidence |
|---|---|---|
| ordinary code change | owner branch/PR, falsifying regression, common gate, fresh actual-diff review, latest CI | exact source/test receipt |
| Platform native or Mod change | Platform exact build/install/cold-load and owning Human gate when applicable | old/new BOM, artifact and loaded identity; no gameplay claim from portable tests |
| collection-tool/Evidence change | immutable new tool/package, pin update, tamper/restart/failure tests and terminal preflight | old tool, old outbox and original failed receipts |
| Hub/worker update | pause dispatch, verified private backup, exact source/lock/image, compatible schema, fresh service smoke | old image/config, closed snapshot, new load receipt |
| failed upload | inspect typed incident; fix transport or owning verifier; explicit retry only where supported | original bytes, intent, receipt and error code |
| native recording defect | report to Platform with exact version and private session evidence | original failed decision/lineage; no cloud-side repair of native truth |
| research projection/model defect | report to STPD; new versioned derived artifact/run after regression | immutable source and previous results, including failures |
| lost/revoked device | revoke its token; issue a new device credential via operator procedure | source data and audit events are not deleted |
| Hub loss | restore private closed DB into fresh state, paused/budget zero, reconcile actual remote attempts | tested recovery receipt and old state; Registry is not a DB backup |
| ambiguous GPU submission | reconcile provider-owned execution/stop truth before new attempt | durable attempt/fence; elapsed time is not proof of stop |

Use local typed status for everyday diagnosis; it is not a substitute for an independently
configured alert destination. Do not claim off-host outage notification until that destination
and failure delivery have actually been tested. Whole-host recovery includes external config,
secrets, certificate state and provider access; a SQLite restore alone does not prove it.
Retain complete incident evidence privately. Public issues/PRs contain redacted findings and
identities, never raw sessions or credentials. Reproduce on the exact version, fix the owner,
add a regression, publish new artifacts, then canary before expanding distribution.

One Hub with SQLite and one active verifier is the deliberate initial scale. Measure queue age,
verification wall time, disk/scratch and worker memory before raising limits. Many collectors
upload directly to R2; they do not each need another Hub. If demand outgrows this measured
capacity, replace the staging/provider/operational mechanism behind existing contracts. Do
not add a second native ledger, research admission service or scheduler source of truth.

## When to freeze the first Full-Run training plan

Freeze the **pipeline and protocol skeleton now**: ownership, immutable IDs, candidate-catalog
contract, complete-run accounting, independent split rules, budgets/stop conditions, evidence
levels and test-set isolation. This does not choose a winning model or establish sufficient data.
The historical combat-v0 10-configuration study and S1 checkpoint are separate preserved lanes;
they are not silently promoted to a Full-Run v1 protocol.

Freeze the **complete executable v1 experiment plan after** real collection/admission profiling
and a separately authorized bounded worker engineering canary, **before** architecture comparison,
selection training or inspecting final holdout outcomes. Keep the pipeline repair PR free of
model-selection changes. The research plan is a reviewed STPD protocol/config PR with:

- immutable admitted Dataset/source IDs, rights/attestation, complete run counts and coverage;
- whole-run/duplicate-component train/dev/test split and sealed test/Gold access policy;
- exact game/Platform/tool/STPD, representation/tokenizer/Qwen/weight pins and supported domains;
- measured candidate/token distributions and fixed representation/overflow policy; no hidden
  truncation or legality reconstruction to make large examples fit;
- primary task, baseline/control families, seeds, optimizer/schedule/steps, checkpoints and
  deterministic resume semantics; Human imitation is not an optimal-action label;
- resource/elapsed/credit limits, cancellation/retry/unknown policy and engineering stop gates;
- predefined evaluation metrics, uncertainty reporting, selection rule and failure thresholds;
- model artifact/adapter support contract and bounded local Shadow/One-Step/Auto evaluation plan.

Three independent run components are only the current technical minimum for train/dev/test,
not evidence of a statistically useful population. Choose collection targets from measured
surface/selector/potion/event/rest/rapid-path coverage and run diversity, not an arbitrary
record total. Additional data creates a new frozen Dataset; it never changes an in-flight Run.
A later protocol amendment creates a new identity and explains what must be re-evaluated.

## Ordered remaining gates

| Gate | Exit evidence | Human/external dependency |
|---|---|---|
| engineering/operations closeout | exact reviewed sources, current CI, deployed image, backup/status and terminal preflight | existing authorized host/accounts only |
| first real Close-to-cloud | new immutable session -> identical local/remote IDs and receipt; no unexplained enrollment | Human gameplay and scoped upload/attestation |
| real Dataset freeze | independent complete runs, coverage/profile/admission/split report | enough authorized real data |
| bounded worker canary | exact image/Qwen/input, budgeted invoke, result readback, checkpoint/recovery | explicit compute allowance and qualified weights |
| full v1 protocol freeze | reviewed executable plan above; sealed test policy | scientific scope/budget approval |
| v1 training and offline selection | immutable results and predefined dev/control criteria | authorized compute; no policy-quality inference from job completion |
| local model evaluation | exact model download + compatible adapter; Platform-owned runtime canary | separately authorized Human/runtime gate |
| cloud game/inference/RL | separate ADR, authoritative environment/license/resource qualification | outside B v1; no simulated legality shortcut |

Training can finish without a supported Full-Run gameplay adapter. Downloading a checkpoint or
inspecting `project policy` never loads a model into the game. Build and qualify that adapter
against the complete Platform catalog before claiming the last mile is complete.

## Capacity and admission are stage-specific

The Hub transport accepts at most 512 MiB compressed, 2 GiB expanded and 50,000 files.
The current STPD bundle3 research adapter independently bounds expanded input to 256 MiB
and 20,000 files. A structurally verified receipt can therefore precede a size-related
projection rejection. Expose both stages; measure the first real complete-run bundles before
changing limits, and rerun resource/abuse regressions for any increase. Do not turn a transport
success or an automatic retry into research admission.

## Read-only local and cloud visibility

Use the [project console guide](PROJECT_CONSOLE.md) for daily operation and
[ADR-0005](adr/0005-local-cloud-console.md) for ownership. The same console serves
local device status and the protected cloud portal. Local setup retains a device
credential; cloud browser login is separate and cannot control a collector.
Deployment of code does not qualify a Cloudflare Access application or an actual
browser login. The Hub runbook records that external activation gate. No GPU is
started by opening any console page.
