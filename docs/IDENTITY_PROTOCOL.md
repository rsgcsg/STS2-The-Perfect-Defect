# Personal identity and developer device connection

This protocol connects a Human-approved browser identity to a local workbench. It does
not attest gameplay, enroll recordings, grant a campaign's upload consent, run a game or
change a Dataset. Cloudflare Access owns Human authentication. The Hub operations database
owns device credentials, stable ownership, approval flows and personal read sessions.
The local workbench keeps credentials outside browser JavaScript and calls these APIs.

## Three separate authorities

- Browser: the Hub verifies the Access application JWT signature, issuer, audience, time,
  email and subject. Stable `principal.subject` is SHA256 of the JSON `[issuer, sub]` pair.
  Current allowlist membership grants role, explicitly shared devices and permission to enroll.
- Device: a revocable credential belongs to one logical device. It permits existing uploads,
  own receipts and the existing shared developer-result reads. Website logout does not revoke it.
- Personal local session: an opaque expiring token grants the same scoped console metadata
  available to its Human principal, plus its own logout. It never authorizes uploads, raw
  payload downloads, jobs, admin operations or a device heartbeat.

The private Access allowlist keeps schema `stpd/console-access-v1`. Each entry accepts
`email`, optional exact provider `subject`, `role`, `devices` (now allowed to be empty), and
optional `enroll_devices` (strict boolean, default false). Operator role alone does not enroll.
For example, an explicitly approved new collector can have `devices: []` and
`enroll_devices: true`. This is an account permission, not campaign consent.

Effective personal device visibility is the union of the current explicit device list and
devices already owned by that stable subject. Disabling enrollment stops future enrollment;
it does not erase existing ownership or evidence. Removing membership invalidates personal
reads; a role change changes research metadata visibility. The configured allowlist is loaded
at Hub startup, so changes require its controlled restart. Device revocation is independent
and affects subsequent device authentication immediately. Existing accepted uploads and
immutable records remain intact. A previously signed R2 PUT grant retains its bounded lifetime.

## Local connection flow

All times below are UTC RFC3339 strings. Flow IDs are 32 lowercase hexadecimal characters.
The local process generates at least 32 random URL-safe characters as `client_secret`, stores
it privately before starting, and never places it in a URL, browser storage or a log.

1. `POST /v1/identity/flows` with `{client_secret, device_name}`. To connect a legacy/current
   device, also supply both `device_id` and its existing `device_token`. An invalid token,
   different logical device or partial proof fails closed. Response:
   `{flow_id, approval_path, expires_at, user_code, poll_interval_seconds: 3}`.
   `approval_path` is always `/app/?view=connect&flow=FLOW_ID`; arbitrary callbacks are rejected.
   Creating a flow does not register a device or create a personal session.
2. Open that path in the authenticated cloud browser. `GET /app/api/identity` returns
   `{principal, devices, observed_at, csrf_token}`. `GET /app/api/identity/flows/FLOW_ID`
   returns `{flow_id, device_name, device_id, user_code, purpose, expires_at, status,
   approval_allowed, recording_consent}`. The Human compares the displayed code with the
   local workbench and reviews the requested device and purpose before approving.
3. `POST /app/api/identity/flows/FLOW_ID/approve` with `{csrf_token, user_code}`. The JWT,
   strict same-Origin value and access-session-bound CSRF token are all required. Origin
   comes from the operator's existing HTTPS `--public-url`, never a forwarded request header.
   Missing/invalid HTTPS origin disables approval. Success returns `{status: "approved"}`.
   `/deny` accepts the same proof and returns `{status: "denied"}`. Approval is one atomic
   transition: concurrent/repeated approvals cannot issue a second credential.
4. `POST /v1/identity/flows/FLOW_ID/poll` with `{client_secret}`. Pending/expired/denied
   responses contain only `status`. Approved response contains
   `{status, session_token, expires_at, principal, device: {device_id, name, token?}}`.
   `device.token` appears only for a newly created device; an existing token is never echoed.
5. Persist the result to private local credential storage, then
   `POST /v1/identity/flows/FLOW_ID/ack` with `{client_secret}`. Acknowledgement is idempotent;
   subsequent polls return denied. A response lost before acknowledgement can be fetched
   again without creating a new device, session or upload identity.

Pending/results are bounded to ten minutes. Approved tokens are domain-separated HMAC
derivations of the Hub identity key, flow ID and client-secret hash. SQLite stores credential
hashes only; it stores no clear device, personal or client secret. Result replay requires
the correct client secret, the same master-key version, live personal membership/session and
an unchanged active newly issued device credential. A Hub restart with the same key preserves
recovery. Rotating the admin-derived master key invalidates uncollected flows; already delivered
personal sessions retain their stored hash and expiry. After ten minutes, start a new connection;
do not infer that an unacknowledged device was never created or erase its evidence.

An existing unclaimed device can be bound only when the approving Human has current explicit
device scope and the flow proved its active device credential. An already owned device can
reconnect only to the same stable owner. Account switching cannot steal or relabel a device.
New enrollment requires `enroll_devices: true`; ownership alone permits later reconnection.

## Reads, logout and device observations

`GET /v1/identity/me` uses the personal Bearer token and returns the identity projection without
CSRF. `principal` has `{subject, email, role, device_ids, research_metadata, enroll_devices,
read_only}`. `devices` contains `{device_id, name, active, last_seen, presence, ownership}`.
Missing registration/activity observations are null, never assumed current. Email is exposed
only to that authenticated principal; another device's owner identity is not returned.

`GET /v1/identity/console/{overview|collections|collections/ID|datasets|datasets/ID|jobs|models|models/ID|system}`
uses the same safe `stpd/console-v1` projections as the browser. Both personal and browser
console reads accept `device=DEVICE_ID`, which must be a subset of the current principal's
devices; unknown/duplicate filters fail closed. Collection scope changes; shared project
Dataset/job/model permissions do not become per-device research admission.

Personal sessions expire no later than 24 hours or the approving Access JWT, whichever is
earlier. Current membership, role and owned/shared scopes are evaluated on each read.
`POST /v1/identity/logout` deletes only that personal token and is idempotent. It does not
revoke a device, stop a local worker or sign out the separate browser Access session.

`GET /v1/identity/device` uses only a device credential and returns
`{device_id, name, active: true, last_seen, presence}`. A personal token cannot substitute.
`POST /v1/identity/device/heartbeat` accepts `{}` or `{version: STRING}` and records the
observation time, not a promised online state. Version is bounded metadata, not build proof.
The existing `/v1/*` upload and artifact permissions remain separate and unchanged.

## Bounds, maintenance and validation

Identity request bodies are at most 8 KiB for create and 1 KiB for approval/poll/heartbeat.
The Hub keeps at most 1,000 unexpired flow rows, 32 current personal sessions per Human and
128 owned devices per Human. Public creation is limited to 20 requests/minute and polling/
acknowledgement to 300/minute per actual socket source; all requests behind a single trusted
reverse proxy share its socket-source limit. Arbitrary forwarded IP headers never relax it.
Rate storage is bounded to 2,048 keys in the current minute. No public endpoint lists flows.

Operations schema 3 adds identity tables and device metadata atomically to schema 1/2. Original
device IDs, token hashes, uploads, receipts, jobs and audit records are preserved. Back up with
the qualified predecessor image before migration and preserve that snapshot plus exact image.
Never point schema-2 software at schema-3 live state. Current backup/restore uses schema 3;
whole-host recovery still includes the separate private allowlist, master key and deployment.

`python -m stpd.hub rotate-device --device EXACT_DEVICE_ID` reads the replacement credential
only from `STPD_DEVICE_TOKEN`. This explicit operator operation replaces the credential hash,
restores device access, invalidates the old credential and appends an audit event, preserving
ownership and all old upload identities. It cannot repair an existing Platform outbox incident;
that owner's authentication-block/recovery protocol is separate. No direct SQLite edits or
transport-file deletion are supported recovery mechanisms.

Portable regressions exercise actual signed JWTs, expiry, origin/CSRF/replay, same-device proof,
account switching, concurrent approval, rollback, response-loss recovery, token confusion,
scope changes, logout, rate limits and legacy schema/credential/upload preservation. They do
not establish real Access login, production TLS, terminal usability or Human-origin evidence.
