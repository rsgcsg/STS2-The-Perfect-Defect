# Project console: local collection and cloud visibility

The project uses one browser interface in two modes. The local console runs beside the
collector and connects to Hub with the existing device credential. The cloud console is a
login-protected team view of data that has actually arrived. They share presentation, not
credentials or authority. [ADR-0005](adr/0005-local-cloud-console.md) defines this boundary.

## Daily collection

Run the approved developer combination through the existing entry:

```bash
uv run --locked python -m stpd.workbench project doctor --config /ABS/project.json
uv run --locked python -m stpd.workbench project open --config /ABS/project.json
```

The browser shows the actual loopback address. The device token stays in the private process
environment. It is not pasted into a web form and is never sent to a third-party browser
identity provider. After setup, ordinary uploads do not require a fresh cloud browser login.

The Human uses the qualified game Mod to record and presses Recorder **Close**. The delivery
service packs a sealed collection, uploads its bytes and reconciles the exact remote receipt.
The collection page separately shows recording quality, delivery and research use. A session
may contain several runs or a partial run; the unassigned session context is not another game.

Closing the browser tab does not stop delivery. `project stop --config /ABS/project.json`
stops the owned background service. After a computer restart or an explicit stop, reopen the
same configuration to resume sealed work. This is not an installed OS autostart service.
Local raw sessions and bundles are not automatically deleted after cloud success.

## Cloud login and connection

Choose **打开云端** from the local page, or open `https://<hub>/app/` from another device.
Cloudflare Access handles browser sign-in; the Hub verifies its signed identity and applies
the operator's role/device allowlist. Device uploads continue through `/v1/*`, independently
of browser cookies. Do not distribute Hub admin/R2/Modal credentials to collectors.

The local collection detail links to the exact remote `upload_id`; the content identity is
checked before remote detail is associated with a local row. The cloud page never reaches
into localhost or remotely controls the game. It can show received records while the collector
computer is off, but it cannot know that computer's unuploaded queue or online state.

The public Hub landing page contains a login link. Protected routes are unavailable until
browser authentication is configured. Activation and role configuration are documented in
the [Hub runbook](../deploy/hub/RUNBOOK.md). A running API does not prove a successful browser login.

## Pages and interpretation

| Page | Purpose |
|---|---|
| 概览 | local/authorized cloud counts, known quality totals and the latest collections |
| 采集记录 | paginated sessions, native run boundaries, owner quality, transfer stages, receipt and timeline |
| 数据集 | authorized immutable Dataset metadata, source references and research usage |
| 作业 | bounded read-only job/attempt/result state and compute limits |
| 模型与评估 | authorized existing artifacts/lineage; local download receipts remain distinct from loading |
| 系统 | connection, source/lock, role scope, available backup state and explicit operational non-claims |

“已录入” means durable canonical decisions. “真实失败” comes from Platform authoritative
disposition, not free-text error matching. Normal cancellations, diagnostics and unsupported
non-decisions are separate. Failed decision evidence may be successfully uploaded and remains
valuable for maintenance. “云端已验收” means receiver integrity/contract verification; it is
not a Human-origin, complete Full-Run, research-admission or model-quality certificate.

Unknown archival quality is shown as unknown. Global quality counters identify missing/partial
summary coverage; the first page is not used to estimate all history. Research admission depends
on a selected input set and exact code, not just one uploaded collection. Dataset references
show actual use without inventing a current admission report for unassessed data.

Upload attempts include normal receipt checks. A stale cloud connection preserves the latest
confirmed receipt and its observation time. No percentage/ETA or historical phase timestamp is
fabricated. The list supports 25/50 rows; the search box explicitly filters only the current page.

## Existing data and upgrades

New verified data materializes safe summaries through the owning APIs. Existing immutable
bundles and receipts retain their original IDs. To populate old local metadata, stop the owning
delivery worker and explicitly run the Platform `delivery_cli summarize` command described in
its version-pinned DELIVERY guide, then reopen the project. This re-verifies existing bundles;
it does not repack, upload, reinterpret failed dispositions or change prior receipts.

The Hub operator uses `console-refresh` to index existing verified artifacts. Browser GETs never
perform this work. Updating code or an index is not permission to enroll historical Human data
in a new consent scope. Upgrade the exact developer combination, never just a sibling import.

## Incidents and future work

Inspect the collection detail for the owning error, exact IDs and last confirmed stage. Preserve
the original recording, bundle and receipts. Public issue reports contain reviewed, redacted
summaries; private evidence is transferred only within its authorized scope. Repair the owning
repository, add a regression, publish a new exact candidate and canary it. Do not erase failures
or copy credentials into screenshots, issues or chat.

This first cloud console is read-only. Jobs, budgets, device grants and recovery mutations remain
with the owning CLI/SSH procedures. Zero launch budget does not stop an already active provider
job. There is no new Full-Run model adapter or live model activation button. Offline/online
evaluation, cloud game/RL and scientific qualification have separate contracts and gates.

The system page is not an outside-host alerting service. A backup status is not the backup bytes,
and an SQLite restore is not whole-host disaster recovery. Missing evidence is displayed explicitly.

After upgrading checkout/dependencies, `project status` and `project stop` can still
address the predecessor's validated local runtime even if its combination is old.
Starting a new service, doctor and model downloads still require current setup.
Stop first, run explicit replacement setup with the preserved campaign/configuration,
rebuild summaries while delivery is stopped, then reopen. No manual process kill is needed.
