# Developer B pipeline operations

This is one STPD developer workbench consuming one independently released Platform Mod and
its public collection tools. Repositories stay separate and packages are exact pins. Models
are separate immutable artifacts. This scope connects existing research services; it does
not add a Full-Run model, Mac Qwen backend, cloud inference, cloud STS2 or RL.

## Authority and data flow

1. Human plays through the existing Platform Mod. Successful Recorder Close durably seals a
   session. The externally running fixed-tool delivery process discovers that seal, records
   an immutable outbox item, packs and verifies it. Unsealed sessions remain local incidents;
   neither timestamps nor upload retries invent native decisions or successors.
2. A revocable developer token requests a short-lived staging upload authorization. The token
   goes only to the Hub; the upload uses the returned capability. Transport retries retain
   exact bytes and IDs. `verification_pending` means wait, never upload again.
3. The CPU Hub independently checks archive hash, bounded inventory and pinned Platform
   verifier. It publishes an immutable received evidence artifact and verified/quarantined
   receipt. Quarantine preserves the submitted archive for maintenance. A network/disk/worker
   resource failure gets bounded retries and then `transfer_failed`, not fake semantic failure.
4. STPD reopens the original received archive and independently projects its occurrences,
   parent/root lineage, execution action-space, Read, Commit and causal successor. This creates
   a source artifact, not permission to train. Diagnostics and real failures remain distinct.
5. An operator freezes an explicit set of received IDs. Existing admission checks complete
   run accounting, failures, semantic duplicates and whole-run component splits. At least
   three independent components are required; two good runs do not satisfy train/dev/test.
   Dataset publication and loading rerun the source projection. More uploads create a new
   Dataset when explicitly selected; they never mutate a training job's input.
6. CPU preparation creates a ModelView and FeatureJob with the expected qualified Qwen
   identity, serializer and training configuration. Hub does not load Qwen. One budgeted
   disposable Modal worker compiles features; CPU validation then freezes TrainingInput/Run.
7. A separately budgeted worker trains using the existing implementation. Checkpoints, model,
   dev evaluation and baselines go to immutable storage. Workers publish candidates; the Hub
   validates exact request/source/plan/bytes and fences selection in its operations database.
   A pause checkpoint is not a completed model. Resume keeps the same frozen Run and supplies
   the exact checkpoint in a new budgeted attempt.
8. Developers view status and download selected result artifacts with hashes and provenance.
   Parent references remain intact, but raw data is not downloaded as a hidden parent closure.
   Download success does not establish model-load, real-game behavior or scientific quality.
   `project policy` starts only an explicitly configured existing adapter; it does not start
   gameplay or supply a new Full-Run inference implementation.

## Developer terminal

Install Git, Python 3.11/uv, Node 20+, the game and the one exact Platform Mod. The fixed .NET
collection tool needs its declared .NET runtime; developers do not rebuild it per session.
Clone STPD; cloning Platform is optional for development, never a sibling Python import.

```bash
uv sync --locked --all-extras
npm ci
uv run --locked python -m stpd.workbench project setup --hub-url https://HUB \
  --delivery-config /ABS/delivery.json --platform-url http://127.0.0.1:PORT
uv run --locked python -m stpd.workbench project doctor
uv run --locked python -m stpd.workbench project open
uv run --locked python -m stpd.workbench project status
uv run --locked python -m stpd.workbench project stop
```

The Platform-owned delivery config is documented in its Evidence DELIVERY.md. It binds the
recording/outbox/tool absolute paths, externally pinned tool release, worker/campaign and
operator Human-origin attestation. Do not silently attest future sessions or reuse an outbox
after changing identity. Set `STPD_HUB_TOKEN` in the process environment; it is a developer
credential, never the admin token. `open` supervises delivery while running. Closing the
workbench stops background processing; sealed items reconcile on the next open.

All active developer identities can read shared result kinds (model, checkpoint, run result,
offline/live evaluation, performance and analysis) and redacted job status. Uploads and their
incidents remain device-scoped. Source/Dataset/raw payloads and mutations are admin-only.
This is a trusted developer group, not tenant isolation or a public collection product.

## CPU Hub operator

Use an exact clean STPD checkout/image. The same locked package supplies Hub and workers.
`STPD_HUB_ADMIN_TOKEN` and `STPD_DEVICE_TOKEN` stay env-only in commands. The admin creates
one distinct device credential per terminal; tokens can be revoked without deleting evidence.
See [deployment](../deploy/hub/README.md) for TLS, mounts, limits and recovery.

Common arguments are `--root /opt/stpd --state /var/lib/stpd/hub --store s3 --staging s3`.
Local development uses a local store and loopback staging instead.

```bash
python -m stpd.hub register --device developer-01
python -m stpd.hub serve --budget-units 0
python -m stpd.hub dataset --received RECEIVED_ID_1 --received RECEIVED_ID_2 --seed 0
python -m stpd.hub feature-job --input-id DATASET_ID --spec /ABS/feature-spec.json
python -m stpd.hub enqueue --kind feature --input-id FEATURE_JOB_ID \
  --request-key FEATURE_REQUEST --max-seconds 300 --reserved-units 1 --budget-units 2
python -m stpd.hub prepare-run --input-id FEATURE_JOB_ID --feature-id FEATURE_SET_ID
python -m stpd.hub enqueue --kind training --input-id RUN_ID \
  --request-key TRAIN_REQUEST --max-seconds 300 --reserved-units 1 --budget-units 2
```

For remote operation append the common arguments to every command; otherwise these examples
use local directories. Feature specs use the strict FeatureJobSpec codec. They contain actual
qualified backend identity, not a guessed GPU dtype/version. Pass `serve --modal-target /ABS/target.json --budget-units N` only for the deployed exact
Modal target. Jobs remain queued without this configured target and nonzero budget. The
target native timeout must not exceed each job's approved maximum. Reservations are conservative campaign
units, not a provider billing meter; consumed reservations do not automatically refund.
The operator must also set provider spend limits and an approved timeout/GPU/concurrency.

## Failure and maintenance

- Operations SQLite is authoritative mutable state; Registry/DuckDB are rebuildable views.
  Back up SQLite using `python -m stpd.hub backup --backup /ABS/new.sqlite`. The consistent
  backup restores paused. Do not copy only a live WAL database file, delete operational state
  to clear jobs, or run a restored Hub beside the original against the same external work.
- Submission uncertainty never resubmits. Lease expiry never means a worker stopped.
  Cancellation acknowledgement alone is not proof of termination. Reconcile actual provider
  stop evidence using `reconcile --job ID --evidence REF`; then explicitly create any new job.
- Pause stops scheduling/monitoring; it is not provider cancellation. An already running
  external job may continue charging. Inspect/cancel it through the recorded provider call.
- Verification runs one bounded child at a time (Linux address space 1.5 GiB, CPU 120 s,
  wall time 150 s). Archive limit is 512 MiB, full expanded stream 2 GiB, files 50,000 and
  intent JSON 32 MiB. Resource failures remain distinct from verifier findings. Review measured
  legitimate failures before changing limits; never make them semantic PASS.
- Quarantined archives, original transfer/receipt and producer/lock/tool identities support
  reproductions. Fix the owning source and add regression tests; publish a new tool/source
  version and new derived artifacts. Never rewrite old evidence or reinterpret old statuses.
- `retry-upload --upload ID` explicitly reopens a failed transfer with its original intent;
  it does not edit its bytes or retry any game action. A local permanent incident needs an
  explicit new delivery attempt after cause repair; do not erase it to fake success.
- Keep raw recordings/outbox until verified remote receipt and tested backup/retention policy.
  No automatic raw deletion is enabled. Staging expiry must be longer than the upload/retry
  window; receipts and trusted artifacts have a separate retention policy.

## Qualification and required human actions

Portable gates cover data/transport/worker mechanics and exact-source CPU subprocesses.
Cloud qualification still requires actual private object-store conditional publication,
multi-part/network interruption, scoped revocation, OCI identity, bounded Modal execution,
output readback, cancellation ambiguity, backup/paused restore and cleanup. Do not promote
fake Qwen or local HTTP tests into GPU/native/scientific evidence.

An owner must supply or authorize the CPU host/domain, R2 account/private buckets and scoped
credentials, Modal account/billing/credentials, immutable image registry and explicit spend
cap. Initial deployment keeps training disabled. After service smoke, enable one short job
under the approved cap. Existing research backbones/weights have their own admission gate.
Final Human collection starts with the one qualified Mod/tool/config and tests actual
Close-to-remote receipt. Missing independent complete runs remain a data gate; no historical
source cropping or relaxed admission is part of B.
