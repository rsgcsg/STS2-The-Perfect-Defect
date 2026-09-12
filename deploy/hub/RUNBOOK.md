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
capacity/retention review. No local/remote backup is automatically deleted. Monitor disk and
bucket growth; retention must preserve a tested compatible recovery point.

For daily scheduling, an administrator puts the reviewed helper and `backupctl backup` into
an external root-owned mode-0700 `/etc/stpd/backup-daily.sh` using the exact image digest. It
must use `set -eu`, fixed absolute paths, and preserve a nonzero exit on failure. Add this entry
to root's crontab using `sudo crontab -e` after manually proving the command and retrieval:

```cron
15 3 * * * /usr/bin/flock -n /run/lock/stpd-backup.lock /etc/stpd/backup-daily.sh >> /var/log/stpd-backup.log 2>&1
```

Pre-create `/var/log/stpd-backup.log` as root mode 0600 and configure bounded log rotation.
Alert on failed runs or backup age over 26 hours; cron output alone is not monitoring. Take an
additional backup before deployments. Keep Caddy TLS state and external config/secret recovery
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
`MODAL_TOKEN_SECRET`. Never put credential values in command arguments or logs. The worker's
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
explicitly retained as uncertain; stopping Hub does not stop a cloud GPU.

```bash
dc stop caddy hub
backupctl restore-check --receipt EXACT_BACKUP_RECEIPT_SHA256 --destination /var/lib/stpd/backups/recovery-verified.sqlite
sudo python3 deploy/hub/preflight.py --backup /srv/stpd/hub/backups/recovery-verified.sqlite
STPD_RETIRED_STATE="/srv/stpd/hub.before-restore-$(date -u +%Y%m%dT%H%M%SZ)"
sudo mv /srv/stpd/hub "$STPD_RETIRED_STATE"
sudo install -d -m 0700 -o 10001 -g 10001 /srv/stpd/hub /srv/stpd/hub/work /srv/stpd/hub/backups
sudo install -m 0600 -o 10001 -g 10001 "$STPD_RETIRED_STATE/backups/recovery-verified.sqlite" /srv/stpd/hub/operations.sqlite
dc up -d
hubctl status
```

The retired directory, including WAL/shm/scratch, remains untouched for audit. Only an API-made
closed backup goes into the fresh directory; do not carry stale WAL/shm files across. Verify
private objects, receipts and deployment identity, reconcile remote attempts, then explicitly
unpause. Perform a full restore rehearsal on an isolated host; do not claim restoration from
merely observing that a backup file exists.

## Deploy, rollback and retire

Pause dispatch, take/off-host-verify a backup, retain current digest/config identities, and
review compatibility before changing `/etc/stpd/deployment.env` to a new exact image. Re-run
preflight and `dc config -q`, pull the image, recreate the service, and verify actual load plus
receipt compatibility. Recheck every source-bound evidence claim on the new source.

Rollback uses the previous reviewed image/config and a compatible backup. Do not simply boot
old code against a database a newer release has migrated. If compatibility is not established,
restore the matching paused snapshot into a fresh directory using the procedure above. Revoke
compromised device tokens or credentials explicitly; that is independent of image rollback.

Retirement stops services and confirms no paid compute remains. Archive operational receipts,
images/config references and recovery material according to retention policy. Do not delete
state volumes or immutable evidence merely to remove stopped containers.
