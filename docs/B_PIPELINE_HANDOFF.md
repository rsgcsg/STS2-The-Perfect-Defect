# Project workflow: download, collect, view and maintain

This is the default developer workflow for the whole project. The B pipeline is its current
implementation: one Platform game Mod, one STPD workbench, one protected cloud portal and
separately downloaded models. [B operations](CLOUD_PIPELINE_B.md) owns data/worker commands;
the [Hub runbook](../deploy/hub/RUNBOOK.md) owns deployment and recovery commands;
the [console guide](PROJECT_CONSOLE.md) explains the screens and account/device behavior.
Do not maintain a separate set of setup instructions in a campaign or chat transcript.

The project cloud entry is [hub.2-fire-2.com](https://hub.2-fire-2.com/). Its account page is
protected; it is not a public dataset browser. Select the exact supported combination from
reviewed release notes, then follow this guide. A branch name or an old private candidate ZIP
is not a release identity. Current bounded qualification is recorded in
[the unified workflow release report](evidence/B_UNIFIED_WORKFLOW_RELEASE_2026-09-13.md).

## The everyday path

| When | What to do | What confirms success |
|---|---|---|
| first install | obtain the approved Mod/tool and exact STPD checkout; run the launcher below | local workbench opens; project doctor passes |
| first connection | log in with an invited email, compare the pairing code, approve this computer | the same named computer appears locally and in the cloud |
| before first recording | obtain the operator's dedicated campaign configuration and explicitly authorize its upload/Human origin | delivery preflight checks the intended recording root and outbox |
| each collection | open the same campaign, record in the game, press Recorder **Close** | collection detail reaches **云端已验收** with an exact remote receipt |
| inspect data | use **采集记录** locally or in the cloud; use **这台电脑** for the local queue | recorded/failed counts, upload stage and research use are shown separately |
| finish or reboot | use `project stop` when stopping delivery; open the same configuration after reboot | retained sealed work resumes under the same device and IDs |
| upgrade or report a problem | follow the upgrade/incident procedure below | old evidence is retained and a new exact candidate has its own checks |

An uploaded collection is not automatically a Dataset or a training launch. The ordered
research gates below remain explicit, with compute launch budget zero until authorized.

## Download and connect once

1. Choose the reviewed release from [STPD Releases](https://github.com/rsgcsg/STS2-The-Perfect-Defect/releases)
   and its linked [Platform release](https://github.com/rsgcsg/STS2-AI-PLATFORM/releases), or an
   explicitly non-stable developer combination. Verify its
   published hashes and supported operating system. Obtain STPD at the release's exact Git
   commit, the single qualified Platform Mod, and the entire fixed collection-tool directory.
   Use an exact Git checkout for this developer distribution; a generated source ZIP does not
   carry the checkout identity used by the reviewed workflow.
2. Install Git, Python 3.11/uv, Node 20+ and the collection tool's declared .NET runtime once.
   The game must already be owned and installed. Install the Mod using the Platform release's
   exact install/load instructions; do not copy game files from another developer.
3. From that clean STPD checkout, open the workbench. Use the same explicit config path in
   all commands; the launcher's user-state default and the lower-level CLI default differ.
   Replace `/ABS/project.json` with the private path selected for this terminal:

   ```bash
   python tools/open_workbench.py --config /ABS/project.json --hub-url https://hub.2-fire-2.com
   ```

   The launcher installs the locked `cloud` profile and exact Node dependencies. It does not
   select a Git revision, install the game Mod, attach a recording directory or authorize a
   campaign. It preserves existing configuration. Collectors need no model weights, Torch,
   Platform checkout, R2 keys, Cloudflare account or admin token.
4. Open **账号与电脑 → 登录并绑定这台电脑**. Use the invited email and verification code,
   compare the displayed computer name/pairing code and approve in the cloud. Return to the
   local page; it stores credentials privately without copying tokens. Public self-signup
   is disabled. Login authorizes account views; the separate device grant permits background
   upload even after personal logout. It does not authorize recording or attest Human origin.
5. Have the operator attach the dedicated campaign as described below. Save the approved
   launcher command with its exact `--config` path as this terminal's normal entry. Each new
   terminal performs a bounded first Close-to-receipt check before routine collection.

Developers changing code and researchers running the full gate still use
`uv sync --locked --all-extras` and `npm ci`; the lighter collector setup does not replace CI.

## Attach a campaign once; reopen it thereafter

The operator supplies a private Platform delivery configuration bound to the approved tool,
device, Human attestation and initially empty recording root. This is the remaining deliberate
setup step; account pairing alone is insufficient. Follow the version-pinned Platform
Evidence DELIVERY guide for those fields. Do not point a new campaign at a historical archive.

Stop an existing workbench before changing its configuration. Preserve its exact state directory
so its personal session and device credential remain in place. Replace all placeholders with
the approved existing values, including `--platform-url` if the terminal uses it:

```bash
uv run --locked python -m stpd.workbench project stop --config /ABS/project.json
uv run --locked python -m stpd.workbench project setup --replace-config --config /ABS/project.json \
  --state-dir /ABS/existing-workbench-state --hub-url https://hub.2-fire-2.com \
  --delivery-config /ABS/delivery.json --platform-url http://127.0.0.1:PORT
uv run --locked python -m stpd.workbench project doctor --config /ABS/project.json
uv run --locked python -m stpd.workbench project open --config /ABS/project.json
```

Omit `--platform-url` only when it was deliberately unconfigured. Setup with replacement uses
the supplied values; it does not merge omitted settings. Never move a retained outbox into a
different device/campaign to clear an error. A failed doctor blocks collection startup.

For daily reuse, run the saved launcher command or `project open --config /ABS/project.json`.
Pressing Recorder **Close** seals the session; the running delivery service packages and sends
it automatically. Keep the workbench process running until the remote receipt is observed.
The browser tab can close independently. There is no installed OS autostart service.

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

## Release builder and operator responsibilities

B remains a developer distribution, not a one-click player installer. A Platform clone is
needed only by Platform developers or the release builder. Both repositories retain independent
versions and source authority. The approved combination links their artifacts; it does not
create a third source repository or a floating sibling dependency.

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
- project email invitation and browser-approved device enrollment (legacy private token
  provisioning remains an operator recovery route);
- private campaign config, dedicated recording and outbox paths, startup/stop/status commands,
  and the campaign's explicit Human-origin attestation scope;
- supported OS and tested gate, known limitations, rollback and incident instructions.

Do not distribute a developer's `.local`, `.env`, home directory, SQLite or outbox. Never give
collectors R2 access keys, the Hub admin token, registry publish credentials or Modal credentials.
A copied public handoff is a template; it cannot grant consent on behalf of another operator.

Publish the reviewed combination, inventories, hashes and supported OS in versioned release
notes before advertising a download. Include the exact Hub OCI digest/source/lock and rollback
pair separately from the terminal Mod/tool identity. A local generated kit is a candidate until
its distribution location and inventory are verified. The cloud landing page's guide follows
the deployed source; a Git merge alone does not update the running service or collectors.

## Build the reviewed developer download

Use the maintained offline builder from the clean exact STPD checkout. Obtain the Mod,
manifest, current distribution BOM and fixed tool from the independently reviewed Platform
release. Expected hashes/release ID come from that release's trusted inventory; do not simply
trust a manifest downloaded beside unknown bytes. The operator checks compatibility and OS
qualification separately. See the [metadata correction](evidence/B_WORKFLOW_PACKAGING_IDENTITY_CORRECTION_2026-09-13.md)
for why BOM file bytes and tool component/workspace revisions are distinct.

```bash
uv run --locked python tools/package_developer_kit.py \
  --mod-dll /ABS/STS2_PLATFORM.dll --mod-dll-sha256 APPROVED_DLL_SHA256 \
  --mod-manifest /ABS/STS2_PLATFORM.json --mod-manifest-sha256 APPROVED_MANIFEST_SHA256 \
  --platform-bom /ABS/platform-bom.json --platform-bom-sha256 APPROVED_BOM_FILE_SHA256 \
  --collection-tool /ABS/collection-tool --tool-release-id APPROVED_TOOL_RELEASE_ID \
  --output /ABS/new-developer-kit.zip
```

The output directory must exist outside tracked source. The builder rejects changed, extra
or symlinked tool files and existing outputs, and reads no credentials or cloud services.
It preserves the original tool manifest/embedded BOM, packages only named public inputs,
and binds the runtime dependency combination by bytes rather than inventing its rules.
Its receipt reports packaging facts; it cannot certify Human origin, install/load, CI or
service readiness. Identical inputs/source produce identical ZIP bytes.

After final gates, publish that new archive, its SHA256/size, `combination.json` inventory
and independently reviewed release notes as immutable GitHub assets. Download it back and
compare its hash before recommending it. Consumers verify the downloaded archive SHA256
against the trusted release before extraction, for example:

```bash
python -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('/ABS/new-developer-kit.zip').read_bytes()).hexdigest())"
```

The exact Git checkout is still the workbench executable entry; the ZIP contains the Mod,
fixed tool and identity/usage files, not a second copy of the workbench source or an installer.
A corrected release uses a new tag/asset identity; never overwrite the previous archive.

## First terminal and real-upload gate

1. Complete source review/root gates/latest-head CI in each repository. Prepare the exact Mod
   and tool artifacts; an unmerged candidate is explicitly non-stable. Update the STPD pin only
   after the Platform candidate is durable and reviewed. Requalify the final Hub image at its
   new source/lock; old cloud receipts remain historical. No merge transfers runtime evidence.
2. Separate qualification from collection: preserve the synthetic Hub state/prefix and prepare
   fresh collection state/prefix with budget zero, private permissions, backup/status checks and
   no configured GPU target. The public service being healthy is not a Human-upload permission.
3. Invite the account, bind one revocable device through the workbench and prepare its local campaign config. Use a **dedicated
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

Before distributing a new combination, stop the owned local process, retain its configuration,
credentials, raw sessions, bundles and outbox, and move the clean checkout to the reviewed exact
revision. Use explicit replacement setup with the same state/campaign settings, run doctor,
then reopen. The launcher does not silently replace a changed combination. Recheck local/cloud
identity and receipt continuity; repeat the owning native or delivery canary when affected.
Roll back with the recorded compatible source/tool/config pair, never by rewriting evidence.

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

The operator performs a daily check until an external alert channel is separately configured:

| Check | Where | Action when missing or wrong |
|---|---|---|
| cloud reachability and exact producer | public `/health`, then authenticated **系统** | inspect DNS/TLS/host and the deployed digest; a healthy API does not prove login |
| stuck delivery or native failures | **采集记录** detail, last observation, receipt and local queue | keep original bytes; route by the first failing owner rather than re-recording a success |
| budget, pending age and disk pressure | **作业／系统**, `hubctl status` and host disk metrics in the runbook | keep dispatch paused/budget zero; investigate before increasing limits |
| backup freshness and timer | runbook `maintenance.py status` and `systemctl list-timers stpd-backup.timer` | inspect the failed stage and verify a new off-host backup/readback |
| recoverability | isolated restore drill after deployment/schema change and on the operator's review schedule | retain image/config/secret recovery material; prove restored state before trusting it |

Backup failure/status is persisted, but no email/webhook/off-host outage alert is promised.
The console cannot announce its own dead host. Save a redacted issue with exact combination,
OS, timestamp, collection/upload/receipt IDs, typed error and reproduction; link private evidence
through the authorized channel. Never include credentials, signed URLs or raw Human payloads.

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

Use the [project console guide](PROJECT_CONSOLE.md) for screen interpretation and
[ADR-0005](adr/0005-local-cloud-console.md) for ownership. The same console serves
local device status and the protected cloud portal. The invited account gives both shells the
same authorized project view; an independently retained device credential owns background
upload. The cloud cannot control the collector or inspect its unuploaded local queue.
Deployment of code does not qualify a Cloudflare Access application or an actual
browser login. The Hub runbook records that external activation gate. No GPU is
started by opening any console page.

## Member activity preparation

The Hub stores administrator-created `stpd/collection-activity-v1` templates. Each activity
version is immutable and identified by its content hash; a changed policy or game/Mod/tool
combination requires the next version. The template supplies reviewed exact game and Mod
identity, consumer/tool pins, upload-host allowlist and the project-member sharing statement.
It contains no terminal paths or credentials. Hub membership authorizes current member/admin
operations; device ownership must be exact and active when enrolling.

A member selects one version and explicitly declares all three: Human origin for this dedicated
campaign, permission to upload, and permission to share with project members. These are the
operator's declarations, not machine verification of gameplay origin. Login, device approval,
old recordings and previous campaigns never imply this consent. Repeating the same enrollment
returns its original ID rather than creating a second campaign.

Local preparation verifies the exact Platform collection tool and consumer pins, then creates
fresh dedicated recording/outbox directories beneath the workbench's private state directory.
The installed Platform `DeliveryConfig` codec validates the generated inactive configuration.
Preparation does not scan old recording directories, attach an active delivery worker, start
upload, launch the game or alter native configuration. Interrupted preparation retains its files
and fails closed; it never clears a directory that might contain Human evidence.

`native_binding_required` is an explicit remaining step. The operator must bind the new recording
root through the supported Platform Mod/profile configuration and verify the actual loaded
native identity and destination. Reading a configuration file or checking a confirmation box is
not proof of that binding. Only after that owning check and delivery doctor can the application
activate the prepared configuration; the first Human Close-to-receipt gate remains separate.

An enrollment alone does not prove which remote uploads belong to it. The current Platform
upload intent has no enrollment field. Shared-download admission therefore requires an exact
owned upload/device and verified bundle campaign identity match; timestamps, directory names
or a guessed current activity cannot grant access to historical uploads.
