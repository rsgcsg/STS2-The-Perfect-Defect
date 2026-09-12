# B Hub: one exact-source service behind TLS

This is an operational deployment definition, not a provisioned service. Source tests and
configuration checks do not prove Docker load, TLS, real R2, real GPU, availability or budget
qualification. No account creation, paid resource or credential is part of this source tree.

## Frozen shape

Use the same reviewed `linux/amd64` OCI image digest as the disposable worker, built by
[`../cloud-worker/Dockerfile`](../cloud-worker/Dockerfile). It retains an exact clean STPD
checkout and locked environment at `/opt/stpd`. Compose starts one non-root Hub API process;
that process launches **one** verifier subprocess at a time using the owning Hub implementation.
Do not add a second verifier service or scale the Hub against the same SQLite directory.

The verifier imposes Linux address space 1.5 GiB, CPU soft/hard 120/125 seconds, file size
3 GiB, and subprocess wall limit 150 seconds. These are fail-closed resource bounds, not a
claim that every valid package fits. Measure the actual exact Linux image and representative
bundles; resource failures remain retryable operational dispositions. Do not increase limits
just to turn an unexplained failure green.

The Hub container is limited to 2.5 GiB memory, no swap, and two CPU cores. Caddy is limited to
256 MiB. Start with a 4 GiB Linux x86_64 host and sufficient disk for the complete image,
SQLite, backups, scratch and retained evidence; this is a capacity recommendation, not a
price quote or performance qualification. Scratch uses the private disk-backed state volume,
not a multi-gigabyte tmpfs. Root filesystem is read-only, and no Docker socket is mounted.

Hub binds `127.0.0.1:8765`; Caddy owns public 80/443 and forwards to that loopback address.
Both use Linux host networking deliberately: a container bound to its own loopback cannot
be reached with ordinary bridge port mapping. This recipe is not a Docker Desktop/Windows
runtime claim. The host must be trusted and dedicated enough that local untrusted processes
cannot impersonate the loopback API. Host firewall exposes only SSH to administrators and
80/443 publicly; it never exposes 8765.

## Files and operator ownership

- `compose.yaml`, `Caddyfile`: reviewed source configuration. No credentials or mutable tags.
- `deployment.env.example`: non-secret fields copied to `/etc/stpd/deployment.env` and edited
  by the operator with exact worker/Caddy image digests, domain and private directories.
- `runtime.env.example`: key inventory only; human/admin supplies actual values separately in
  `/etc/stpd/hub-runtime.env`, mode 0600, outside Git. Do not source this file into a shell.
- `backup.py`, `backup.env.example`: explicit private operator backup/upload and new-path
  restore-check using the owning SQLite API and a separate credential/bucket; no live restore.
- `maintenance.py`, `stpd-backup.service`, `stpd-backup.timer`: supported daily exact-image
  backup, bounded private last-success/failure status and 26-hour freshness check. Successful
  scheduled snapshots are removed only after verified remote commit. Remote retention and
  outside-host notifications require operator review; neither is silently configured.
- `preflight.py`: read-only configuration, host and already-created backup checks. It reports
  field failures and presence, never parsed values. It does not contact storage or buy compute.
- `ingress-lifecycle.json`: proposed ingress-only rule aborting unfinished multipart uploads.
  Completed ingress objects do not expire automatically; see the lifecycle section below.
- `RUNBOOK.md`: exact bootstrap, operation, backup, restore and rollback steps.

Docker Compose >=2.30 is required for `env_file: format: raw`, preventing interpolation of
credential characters. `docker compose config -q` validates silently. Never paste the output
of unfiltered `docker compose config`, container `.Config.Env`, or an env file into reports.
The Caddy image must include the directives in `Caddyfile`; validate that exact digest before
starting it. The proxy body ceiling is 32 MiB, matching the Hub upload-intent metadata
limit; raw archives upload directly to object storage. HTTP access logging is not enabled; bearer credentials never belong in URLs.

## Storage boundaries and lifecycle

Use distinct **private** ingress, artifact and operator-backup buckets. Disable public development URLs and
public bucket domains. The Hub account needs ingress PUT signing/GET and artifact conditional
write/read/list; lifecycle administration belongs to an operator identity, not to collectors
or compute workers. Collectors receive limited upload permissions from Hub and cannot select
arbitrary object keys. Region, privacy, endpoint and real conditional-write semantics require
separate operator/runtime checks; an HTTPS endpoint alone proves none of them.

`incoming/<upload-id>` is staging. Only a verified or quarantined durable receipt proves that
the raw archive and its transfer/intent/receipt have been published into immutable artifact
storage. `transfer_failed` or `verification_pending` is not a successful archival receipt.
Therefore the default lifecycle removes **only unfinished multipart uploads after one day**,
not completed objects, unverified inputs or incident evidence. Apply it only to ingress, after
reviewing/merging any existing bucket rules. A blanket lifecycle replacement may remove other
rules. No lifecycle is installed automatically by this source package.

After measured operation, an explicit maintenance process can remove a completed staging
object only after checking its durable archival receipt and retained raw payload. Until then,
accept modest staging duplication. Never expire source artifacts, model dependencies, failure
archives or operational backups through the ingress rule. Local clients retain originals while
awaiting cloud receipts; retention is not inferred from an HTTP PUT response.

## Optional scheduling in the same Hub

`STPD_HUB_BUDGET_UNITS=0` and absent optional Modal variables leave the default service in
upload/verification mode. To enable the existing scheduler in the **same Hub process**, an
operator configures `STPD_MODAL_TARGET=/var/lib/stpd/modal-target.json`, `MODAL_TOKEN_ID` and
`MODAL_TOKEN_SECRET` in the external runtime env, then deliberately sets a positive budget.
No second Hub, GPU service or independently polling scheduler container is introduced.

The target JSON must name the exact current source/lock and same reviewed worker image digest.
Its content-derived app namespace must match the deployed Modal function; do not reuse a mutable
name for a different target. The owning scheduler restricts one active job/GPU, checks the target
timeout against each job's maximum, and reconciles uncertain delivery before any replacement
attempt. A positive budget is an operational reservation limit, not a dollar billing guarantee.

Preflight checks mounted target path/private ownership/current source-lock-image identity and
complete credential presence without contacting Modal. It accepts nonzero budgets only with
`--allow-compute`; ordinary preflight keeps the initial zero-budget safeguard. Hub startup still
owns complete typed target validation and runtime producer matching. An exact deployed target,
account authorization, provider limits and bounded real cloud canary are separate prerequisites;
these source files create no account, provision no resource and submit no paid call by themselves.
A restored Hub starts paused and must reconcile external work before unpausing. See the runbook
for explicit enablement and pause procedures.

## Validation available without Docker or credentials

```bash
uv run --locked python -m unittest discover -s deploy/hub -p 'test_*.py' -v
uv run --locked ruff check deploy/hub
python3 deploy/hub/preflight.py --help
```

These test read-only/secret-redaction behavior, malformed env files, non-expiring ingress,
chunked backup round trips, corruption/readback failures, schema/paused checks and new-path
restoration without overwriting existing state. They are not a Docker deployment. The runtime checklist in
RUNBOOK remains required on the real Linux host and exact OCI digests.

Primary references used for the recipe:
[Compose service configuration](https://docs.docker.com/reference/compose-file/services/),
[host networking](https://docs.docker.com/engine/network/drivers/host/),
[Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https),
[SQLite backup API](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup),
[R2 lifecycle](https://developers.cloudflare.com/r2/buckets/object-lifecycles/).
