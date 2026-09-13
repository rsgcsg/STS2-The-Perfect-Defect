# ADR-0005: One local/cloud project console

Status: accepted. Browser activation, deployment and Human usability evidence remain separate.

## Problem and owner

The B pipeline has an operational upload/receipt path, but the developer page presents nested
JSON and the public Hub exposes only machine APIs. A developer cannot easily associate a
Recorder session with its remote receipt, recording quality or subsequent research artifacts.

Platform owns recording dispositions, native boundaries and immutable bundle verification.
Its versioned safe summary and paginated delivery projection are the recording/transport
inputs. STPD never reads the private Platform outbox database or reconstructs validity.
STPD continues to own admission and immutable Dataset/job/model/evaluation lineage.

## Decision

Use one small shared HTML/CSS/JavaScript console with two explicit modes. Local HTTP serves
the shell and composes the owning delivery CLI with device-authenticated Hub queries. The
Hub serves the same shell with authorized server-side projections. No frontend build server,
new message bus, generic plugin framework or second data authority is introduced.

Navigation is overview, collections, datasets, jobs, models/evaluation and system. A collection
is a Recorder session, not necessarily one run. Native run children retain separate boundaries;
the exact unassigned session context is not counted as a game. Recording quality, delivery,
research checks on an input set, and actual artifact use are independent display dimensions.
Diagnostic invalidations and normal cancellations are not recording failures.

The local server retains the device token; the browser never receives it. Local setup connects
the device once, while a cloud link opens the exact remote upload ID and may require browser
login. Cloud pages never query or control localhost. No terminal heartbeat is inferred from an
upload; offline queues remain local and cloud device presence is unobserved.

Cloudflare Access authenticates browser users. Hub verifies signed application JWTs against
the configured issuer/audience and a private principal-to-role/device allowlist. Device Bearer
API remains independent. Browser access is read-only. Authentication does not imply permission
to view every Dataset, raw payload or device; sealed research results remain restricted.
Without complete browser configuration, protected routes fail closed. Anonymous landing and
health routes expose no collection data.

## Read and failure model

GET queries use bounded pagination and verified metadata indexed at owner publication or an
explicit refresh. They do not scan archives/Parquet, rebuild Registry, run admission, start
workers or alter evidence. Indexes are rebuildable and bound to exact content/verifier identity;
index failures cannot change a successful upload or compute disposition.

Visible pages refresh bounded projections without reloading the document. Local and cloud
observations have independent caches and timestamps. A failed refresh retains the last known
receipt with an explicit stale marker; an absent observation is unknown, never a zero count.
Only recorded milestones are shown. Attempt counts include receipt polling, not just failures.

An upload never edits an existing Dataset or starts training. Model receipts/manifests do not
establish actual loading or activation. Full-Run adapters, new models, live/cloud game evaluation,
GPU qualification and a scientific campaign are outside this UI change.

## Validation and operation

Validate owner disposition/archival contracts, pagination past 100 records, query bounds,
identity mismatches, failure/stale recovery, XSS/Host boundaries, JWT expiry/audience/signature,
origin bypass and cross-device scope. Exercise packaged assets in the real browser and preserve
Human bytes/old receipts during controlled summary refresh. Exact source/CI/image and deployed
service qualification are required independently. Browser login and final Human usability are
explicit gates; the runbook documents the shortest operator steps.
