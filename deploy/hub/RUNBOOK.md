# Hub operator runbook

Run commands only after account/region, resource budget and credentials are authorized.
This document is a procedure, not a record that deployment happened. The source checkout,
worker image, Caddy image and deployment config each have an independently recorded identity.
Use an exact clean checkout of the approved STPD revision. Do not edit code on a running host.

## Bootstrap the authorized Linux host

Prepare Docker Engine and Compose >=2.30 using the host vendor's supported installation path.
Use Linux x86_64 with 4 GiB memory initially. Confirm disk capacity for the exact worker image
and scratch, and free ports 80/443/8765. Point the owned DNS hostname at this host. Permit
inbound 80/443 for Caddy's public HTTPS flow and restrict SSH to operator access.

An administrator creates private disk directories (example locations match the env template):

```bash
sudo install -d -m 0700 /etc/stpd
sudo install -d -m 0700 -o 10001 -g 10001 /srv/stpd/hub
sudo install -d -m 0700 -o 10001 -g 10001 /srv/stpd/hub/work /srv/stpd/hub/backups
sudo install -d -m 0700 /srv/stpd/caddy /srv/stpd/caddy/data /srv/stpd/caddy/config
sudo install -m 0600 deploy/hub/deployment.env.example /etc/stpd/deployment.env
sudo install -m 0600 deploy/hub/runtime.env.example /etc/stpd/hub-runtime.env
sudo install -m 0600 deploy/hub/backup.env.example /etc/stpd/hub-backup.env
```

Edit those external files with the intended non-secret settings and credentials through the
operator's secure editor. Generate the admin token with an approved password manager; do not
print it in shell history or share it in chat. Keep the initial budget at zero. Use three distinct private
R2 buckets (ingress, artifacts, operator backups) and exact immutable OCI references. Leave optional Modal variables unset for this initial upload-only load.
Record reviewed source SHA, lock hash, both image digests and a hash of the non-secret config.
Keep the previous deployment config/image identities for rollback; never log the secret file.

Define command helpers in the operator shell; these read the external files through Compose:

```bash
STPD_HUB_COMPOSE_FILE="$PWD/deploy/hub/compose.yaml"
dc() { sudo docker compose --env-file /etc/stpd/deployment.env -f "$STPD_HUB_COMPOSE_FILE" "$@"; }
hubctl() { dc exec -T hub /opt/stpd/.venv/bin/python -m stpd.hub "$@" --root /opt/stpd --state /var/lib/stpd --store s3 --staging s3; }
sudo python3 deploy/hub/preflight.py --config /etc/stpd/deployment.env --host
dc config -q
```

`config -q` is deliberately silent; plain `config` can expose runtime env values. Preflight is
read-only. Missing Docker, credentials, DNS or image identity remains a real external blocker.
Do not treat a source test as permission to skip it.

## First load and verification

Pull only the configured digest references, then validate Caddy without starting the service:

```bash
dc pull
dc run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
dc run --rm --no-deps hub status --root /opt/stpd --state /var/lib/stpd --store s3 --staging s3
dc up -d
dc ps
curl --fail --silent --show-error http://127.0.0.1:8765/health
```

Verify `https://<owned-hostname>/health` from a separate machine and inspect the certificate.
An unauthenticated request to `/v1/status` must be rejected. Check the actual listening sockets
and host firewall: 8765 must be loopback only. Inspect filtered image/container identity rather
than dumping environment variables:

```bash
sudo docker inspect --format '{{.Image}}' stpd-hub
sudo docker inspect --format '{{.Image}}' stpd-hub-tls
hubctl status
dc logs --tail 100 hub caddy
```

Validate a real store's immutable conditional write/readback using the existing owning smoke:

```bash
dc exec -T hub /opt/stpd/.venv/bin/python -m stpd.workbench doctor --store s3 --smoke
```

That command writes a uniquely scoped diagnostic probe; retain its receipt. Test one explicitly
synthetic upload, duplicate delivery, an intentionally invalid test archive and a retryable
transport failure. Confirm verified/quarantined receipt types and one active verifier. Measure
cold image RSS/VAS/CPU and scratch usage against the configured bounds; no real Human upload
is required merely to qualify transport. Only then perform the separately prepared Human gate.

## Register a developer device

Use a new device-specific random token. An operator injects `STPD_DEVICE_TOKEN` securely into
the shell environment; do not put its value on the command line. Docker forwards only its name:

```bash
sudo --preserve-env=STPD_DEVICE_TOKEN docker compose --env-file /etc/stpd/deployment.env -f "$STPD_HUB_COMPOSE_FILE" exec -T -e STPD_DEVICE_TOKEN hub /opt/stpd/.venv/bin/python -m stpd.hub register --device developer-device-01 --root /opt/stpd --state /var/lib/stpd --store s3 --staging s3
hubctl revoke --device developer-device-01
```

The `revoke` line is a separate revocation operation, not the next registration step. After
registration, configure that token and TLS URL in the local project client using its secure
configuration path. Validate identity on that endpoint before allowing an upload. When using
sudo, forward that one explicitly authorized variable with `sudo --preserve-env=STPD_DEVICE_TOKEN`
for the registration command, or invoke Compose from an approved Docker operator account;
never preserve the entire user environment. Do not distribute the Hub admin token to devices.

## Browser console login and local connection

The local project console uses its existing private device token for `/v1/console/*`; it
never needs the Hub admin token or a browser login to upload. Its cloud record link opens
`https://YOUR-HUB/app/#collections/UPLOAD_ID`. Cloud login is separate from device delivery,
so logging out of the website does not stop uploads. The cloud cannot observe an offline
terminal's unuploaded queue. There is no cloud-to-local game control or browser localhost fetch.

Use one Cloudflare Access self-hosted application for exact `/app` and `/app/*` (including
`/app/api/*` and assets); leave `/v1/*` and `/health` outside this browser application.
Use an allow policy for explicitly approved email identities and email one-time PIN or the
team's existing identity provider. Do not create a Bypass policy. Configure no paid plan.
Before enabling browser access, confirm the Cloudflare zone is proxied and TLS is Full (strict).
The Hub validates the JWT at the origin; a spoofed email header or direct-IP request does not
bypass login. JWT key discovery uses only the configured Cloudflare team origin and is bounded.

The account owner supplies the team domain and application AUD after creating the application.
An operator prepares `/var/lib/stpd/console-access.json` in mounted private Hub state, owned
by uid 10001 and mode 0600, using this format with real explicitly allowed devices:

```json
{"schema":"stpd/console-access-v1","principals":[
  {"email":"collector@example.org","role":"collector","devices":["developer-device-01"]},
  {"email":"reviewer@example.org","role":"reviewer","devices":["developer-device-01"]}
]}
```

The optional `subject` pins the exact validated Access subject in addition to email. Roles:
`collector` sees only listed devices' collections and shared result metadata;
`reviewer` additionally sees project Dataset metadata; `operator` also sees private operational
status. No role gets raw/Dataset payload download or write operations through the console.
Research metadata roles are project-wide permissions, independent of the explicit device list.
Use `STPD_ACCESS_ISSUER`, `STPD_ACCESS_AUDIENCE`, `STPD_ACCESS_ALLOWLIST` from the runtime env
example, run preflight, then replace only the exact Hub candidate. Missing configuration keeps
`/app` disabled. Partial or malformed configuration fails startup. Allowlist changes require a
Hub restart; device revoke continues to affect Bearer access independently.

After a candidate changes owner summary support, explicitly rebuild its **derived index** once:

```bash
hubctl console-refresh
```

This reads verified immutable evidence using its existing identity and the installed Platform
summary owner, without replacing original receipts, manifests or raw data. It also indexes
safe metadata from existing artifact manifests. A specific existing upload can be refreshed
with `hubctl console-refresh --upload EXACT_UPLOAD_ID`. GET requests never do this work.
New verified uploads index their summary once. Hub-published Datasets are indexed at creation;
scheduler-selected result manifests and their lineage are indexed after validated result
selection. Artifacts copied by other tools need an explicit refresh. The console states its index scope; missing index data
is not a claim that the object store has no data. Summary failure does not invalidate a
previously successful receiver receipt; it displays `unavailable` and requires owner repair.
If the index or even its failure marker cannot be written, the immutable upload/compute outcome
still remains authoritative. An absent summary is unknown, never zero failures. Dataset CLI and
scheduler completion reports expose `console_index_status` separately; optional index work cannot
change success into a publication/compute failure. Explicit `console-refresh` itself fails visibly
when its requested repair cannot complete; do not suppress failures of that operator command.

The backup panel optionally consumes the existing maintenance owner's bounded status file via
`STPD_HUB_BACKUP_STATUS`; make only that safe projection readable inside mounted state. Do not
mount backup credentials or whole host directories. Absent projection means `not_configured`,
not a claim that backups are failing or passing. Whole-host recovery and external alert delivery
remain unqualified until their own exact evidence exists.

Before real browser qualification, exercise missing/expired/wrong-audience/tampered JWT,
plain email-header spoofing, direct-origin bypass, collector cross-device access, and preserved
raw/Dataset restrictions. Then an allowlisted Human logs in once, checks a known receipt and
confirms local-to-cloud links. This is a login/UI gate, not GPU or new Human recording evidence.

## Normal operations and incident handling

```bash
hubctl status
hubctl pause
dc logs --tail 100 hub
hubctl retry-upload --upload EXACT_UPLOAD_ID
```

Inspect typed upload receipts/findings and immutable run events. `retry-upload` is appropriate
only after resolving a recoverable transfer issue; it does not convert invalid Human evidence
into valid evidence. A native correctness failure stays a Platform issue with its exact source
and session identity. A storage outage does not become a native decision failure.

Check disk, stale pending age, verification failures, backup age and TLS renewal. Keep the
operational queue small; review cold VAS limits before increasing accepted bundle sizes.
Automatic retries are bounded by owning code. A restore or budget pause does not delete queue
entries. Resolve every `uncertain`, `submission_unknown` or `cancelling` compute attempt against
actual provider state before allowing a new attempt:

```bash
hubctl reconcile --job EXACT_JOB_ID --evidence REVIEWED_PROVIDER_STOP_EVIDENCE_REFERENCE
hubctl unpause
```

Those are operator-reviewed facts, not a workaround to erase an unknown delivery. Default
Compose configuration keeps the budget at zero and the optional same-process scheduler unset.

## Consistent private off-host backup

The separate backup container uses the **same exact worker image digest** and the owning
`Operations.backup()` API. It generates a consistent closed SQLite snapshot with `paused=1`,
then uploads SHA256-addressed chunks and a commit receipt to a third private operator bucket.
Every chunk and receipt is read back before success. No ArtifactStore/Registry/research index
is used. Never copy a live `operations.sqlite` alone while its WAL is active.

Configure `/etc/stpd/hub-backup.env` with a separate operator credential restricted to the
backup bucket. Do not give that bucket's credentials to the always-running Hub, collectors or
GPU workers. Disable public URLs and bucket domains. Backups include credential hashes, leases
and private identifiers: account recovery must work without this server. Provider encryption
at rest and TLS plus private IAM are required; client-side encryption/key rotation is a future
independent operational choice, not a property this tool claims.

Set the public image value to exactly the `STPD_WORKER_IMAGE` from the reviewed deployment.
This helper starts an ephemeral bounded container and gives it no Docker socket:

```bash
STPD_WORKER_IMAGE=registry.example/stpd@sha256:REPLACE_WITH_REVIEWED_DIGEST
backupctl() {
  sudo docker run --rm --platform linux/amd64 --user 10001:10001 --read-only \
    --cap-drop ALL --security-opt no-new-privileges --memory 512m --cpus 1 --pids-limit 64 \
    --tmpfs /tmp:rw,noexec,nosuid,size=32m,mode=1777 \
    --env-file /etc/stpd/hub-backup.env --env STPD_WORKER_IMAGE="$STPD_WORKER_IMAGE" \
    --env GIT_CONFIG_COUNT=1 --env GIT_CONFIG_KEY_0=safe.directory \
    --env GIT_CONFIG_VALUE_0=/opt/stpd --env GIT_OPTIONAL_LOCKS=0 \
    --mount type=bind,src=/srv/stpd/hub,dst=/var/lib/stpd \
    "$STPD_WORKER_IMAGE" /opt/stpd/.venv/bin/python /opt/stpd/deploy/hub/backup.py "$@"
}
backupctl backup
backupctl restore-check --receipt EXACT_BACKUP_RECEIPT_SHA256 --destination /var/lib/stpd/backups/retrieval-drill.sqlite
```

The output gives a receipt digest, never credentials or signed URLs. Store it in the protected
operator recovery inventory alongside source/lock/image/config identities. The retrieval drill
verifies receipt/chunk/full-file SHA256, current owning database schema, SQLite integrity and
paused state. The tool refuses an existing destination and never installs a database. A 512 MiB
snapshot limit bounds this first implementation; exceeding it is an explicit failure requiring
capacity/retention review. Manual commands retain their snapshots. The scheduled command uses
`--discard-local-after-verified`: it deletes only its own temporary snapshot after the complete
off-host commit/readback succeeds. Failed snapshots, old files and all remote backups remain
untouched. This flag is not general retention or garbage collection.

### Install and inspect scheduled backup

The supported Linux recipe uses the reviewed `stpd-backup.service` / `stpd-backup.timer`, not
a copied shell function containing credentials. It expects the exact clean deployment checkout
at `/opt/stpd-deploy/source`, Docker already running, and the external env files above. The
runner parses raw values without shell expansion; it reads the current exact image from
`deployment.env` and refuses mutable tags. The image must already be locally pulled. The
ephemeral backup container has only the separate backup credential and the state mount; it
has no Docker socket, Modal credentials or compute scheduling command.

After a manual backup and retrieval pass, install and exercise the actual service once:

```bash
sudo install -m 0644 deploy/hub/stpd-backup.service /etc/systemd/system/stpd-backup.service
sudo install -m 0644 deploy/hub/stpd-backup.timer /etc/systemd/system/stpd-backup.timer
sudo systemd-analyze verify /etc/systemd/system/stpd-backup.service /etc/systemd/system/stpd-backup.timer
sudo systemctl daemon-reload
sudo systemctl start stpd-backup.service
sudo python3 /opt/stpd-deploy/source/deploy/hub/maintenance.py status
sudo systemctl enable --now stpd-backup.timer
sudo systemctl list-timers stpd-backup.timer
```

The persistent timer runs daily at 03:15 UTC with up to 15 minutes jitter and catches a missed
run after boot. `flock` prevents overlapping scheduled runs. A backup has a 15-minute wall
limit; the host runner stops only its exact named container on timeout. An unconfirmed stop is
reported explicitly. Inspect that container before retrying; killing a Docker client does not
prove container termination. No periodic command submits GPU work or changes Hub pause/budget.

Private `/var/lib/stpd-maintenance/backup-status.json` is one bounded atomic operational
projection: latest attempt/result, last verified receipt, timestamp and image. Failed attempts
retain the last successful recovery point. `maintenance.py status` exits nonzero for missing,
failed, interrupted, future-dated or more-than-26-hour-old success. Immutable off-host receipts
remain the authority; this status file is not itself a backup. Copy each verified receipt to
the protected off-host operator recovery inventory; do not depend on this host-local projection
to find the recovery point after host loss.

```bash
sudo python3 /opt/stpd-deploy/source/deploy/hub/maintenance.py status
sudo systemctl status stpd-backup.service --no-pager
sudo journalctl -u stpd-backup.service -n 20 --no-pager
```

Compose already rotates each service's local-driver logs at 10 MiB × 3 files. Backup emits one
small sanitized status per run to systemd journal; journal retention remains the host operator's
existing policy. No SDK stderr, signed URL or credential is published. Inspect disk and bucket
size at least weekly, especially retained failed snapshots. Never expire immutable chunks,
receipts or evidence through an age-only bucket rule: shared chunks may be the only recovery
point. Remote backup GC is deliberately manual until a reviewed reachability-aware process
exists. Preserve at least one tested compatible receipt before authorizing any cleanup.

**Notification boundary:** persistent failure/status is implemented; email, webhook and an
independent outside-host heartbeat are not configured by this tool. Connect the nonzero status
and host/TLS availability to the operator's chosen monitor before claiming unattended alerting.
Until then an operator must inspect status daily; a dead host cannot report its own failure.

Take an additional backup before deployments. Keep Caddy TLS state and external config/secret recovery
material in the protected operator backup system separately; this tool intentionally backs up
only operational SQLite. A successful upload is not a full disaster recovery qualification:
perform the paused restore rehearsal below on an isolated host.

## Enable the existing same-Hub scheduler

Do this only after operator account/budget authorization and qualification of the exact Modal
worker target using `deploy/cloud-worker/README.md`. This procedure does not provision Modal
resources. Deploy the exact target's content-derived app namespace and verify its source/lock,
worker OCI image and resource limits. Do not overwrite a different target under a shared name.
The same Hub schedules at most one active job/GPU; its target timeout must be no greater than
each queued job's `max_seconds`, and reservations must fit the explicitly configured budget.

Pause existing dispatch and save a private backup first. Place the reviewed JSON in the mounted
state directory and set **all three** optional keys in `/etc/stpd/hub-runtime.env` using the
secure operator editor: `STPD_MODAL_TARGET=/var/lib/stpd/modal-target.json`, `MODAL_TOKEN_ID`,
`MODAL_TOKEN_SECRET`, and set `MODAL_ENVIRONMENT=spireagent-b` to match the deployed
worker and Secret environment. Never put credential values in command arguments or logs. The worker's
storage secret belongs to its provider deployment; it is separate from the Hub's Modal token.

```bash
hubctl pause
backupctl backup
sudo install -m 0600 -o 10001 -g 10001 /PRIVATE_OPERATOR/reviewed-modal-target.json /srv/stpd/hub/modal-target.json
sudo python3 deploy/hub/preflight.py --config /etc/stpd/deployment.env --host
```

The first check still uses budget zero and may validate the fully configured dormant target.
Then explicitly change `STPD_HUB_BUDGET_UNITS` in `/etc/stpd/deployment.env` to the authorized
positive reservation limit and validate that opt-in:

```bash
sudo python3 deploy/hub/preflight.py --config /etc/stpd/deployment.env --host --allow-compute
dc config -q
dc up -d --force-recreate hub
hubctl status
```

Retain the selected namespace/target/image identity in the operator inventory. Resolve any
in-flight/unknown provider attempt before `hubctl unpause`. Then enqueue only an approved bounded
canary with the existing Hub/Workbench job commands; inspect attempt fences, deadlines and
candidate validation before increasing workload. No queued job or positive budget constitutes
model-quality qualification. To stop new work, `hubctl pause`; changing env/budget alone does not
cancel an already running GPU. Confirm cancellation/terminal state with the owning scheduler
and provider before disabling the optional variables or rolling back.

## Restore into paused state

First stop API and proxy so there are no writers. Confirm all remote jobs are stopped or
explicitly retained as uncertain; stopping Hub does not stop a cloud GPU. Restore initially
in upload-only mode: through the secure operator editor, remove all three optional Modal
keys from `/etc/stpd/hub-runtime.env` and set `STPD_HUB_BUDGET_UNITS=0` in
`/etc/stpd/deployment.env` before restarting. The SQLite backup does not contain
`modal-target.json`; do not boot with a dangling target path or copy a target whose
source/lock/image differs from the selected recovery image.

```bash
sudo systemctl stop stpd-backup.timer
sudo systemctl stop stpd-backup.service
sudo docker ps --filter name=stpd-backup-
```

Confirm no backup container remains before proceeding; stopping a service/client alone does
not prove container termination. Then stop the Hub and retrieve the selected recovery point:

```bash
dc stop caddy hub
backupctl restore-check --receipt EXACT_BACKUP_RECEIPT_SHA256 --destination /var/lib/stpd/backups/recovery-verified.sqlite
sudo python3 deploy/hub/preflight.py --backup /srv/stpd/hub/backups/recovery-verified.sqlite
STPD_RETIRED_STATE="/srv/stpd/hub.before-restore-$(date -u +%Y%m%dT%H%M%SZ)"
sudo mv /srv/stpd/hub "$STPD_RETIRED_STATE"
sudo install -d -m 0700 -o 10001 -g 10001 /srv/stpd/hub /srv/stpd/hub/work /srv/stpd/hub/backups
sudo install -m 0600 -o 10001 -g 10001 "$STPD_RETIRED_STATE/backups/recovery-verified.sqlite" /srv/stpd/hub/operations.sqlite
sudo python3 deploy/hub/preflight.py --config /etc/stpd/deployment.env --host
dc config -q
dc up -d
hubctl status
```

The retired directory, including WAL/shm/scratch, remains untouched for audit. Only an API-made
closed backup goes into the fresh directory; do not carry stale WAL/shm files across. Verify
private objects, receipts and deployment identity, reconcile remote attempts, then explicitly
unpause. Re-enable compute only through the scheduler enablement procedure with a reviewed
target matching the restored image; the API's successful paused start does not restore that
target or its provider credentials. Perform a full restore rehearsal on an isolated host; do not claim restoration from
merely observing that a backup file exists.
After recovery, manually run `stpd-backup.service`, verify its new off-host receipt and retrieval,
then start `stpd-backup.timer` again. Do not carry a green maintenance status across a restored
state without a new backup.

## Deploy, rollback and retire

Stop the backup timer and wait for any running backup to finish before replacing the deployment
checkout/config. Pause dispatch, take/off-host-verify a backup, retain current digest/config identities, and
review compatibility before changing `/etc/stpd/deployment.env` to a new exact image. Re-run
preflight and `dc config -q`, pull the image, recreate the service, and verify actual load plus
receipt compatibility. Recheck every source-bound evidence claim on the new source.
Install changed service/timer definitions from that exact checkout and `systemctl daemon-reload`.
Prove one backup/retrieval with the new image before restarting the timer. There is no second
hardcoded image pin in a handwritten cron helper to drift from the Hub deployment.

Rollback uses the previous reviewed image/config and a compatible backup. Do not simply boot
old code against a database a newer release has migrated. If compatibility is not established,
restore the matching paused snapshot into a fresh directory using the procedure above. Revoke
compromised device tokens or credentials explicitly; that is independent of image rollback.

Retirement disables the backup timer, stops services and confirms no paid compute remains. Archive operational receipts,
images/config references and recovery material according to retention policy. Do not delete
state volumes or immutable evidence merely to remove stopped containers.

### Source-only image refresh with an unchanged dependency lock

A full worker build temporarily retains downloaded, compressed and unpacked training
libraries. Measure free disk before building on a small Hub; keep the running/rollback
image and all operational/evidence state. Disposable build cache and unreferenced local
image copies may be removed; their public immutable registry objects are separate.

For a source-only update, `deploy/cloud-worker/refresh.Dockerfile` can reuse a previously
qualified exact worker image. It checks a clean parent checkout, an exact new Git revision,
an unchanged `uv.lock`, locked offline synchronization and a clean resulting source. It
fails closed on a dependency change; use the normal full Dockerfile in that case.

```bash
docker build -f deploy/cloud-worker/refresh.Dockerfile \
  --build-arg QUALIFIED_WORKER_IMAGE=ghcr.io/rsgcsg/stpd-worker@sha256:EXACT_PARENT_DIGEST \
  --build-arg STPD_SOURCE_REVISION=EXACT_NEW_HEAD \
  -t ghcr.io/rsgcsg/stpd-worker:EXACT_NEW_HEAD .
```

Record parent digest and recipe with the resulting digest. Rerun latest-head source/CI
checks and independently verify fresh-container source/lock/assets, public service,
R2 and backup/restore. Parent qualification never qualifies changed source automatically.
