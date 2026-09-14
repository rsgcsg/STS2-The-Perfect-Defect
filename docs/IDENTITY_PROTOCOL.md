# Personal identity and developer device connection

This protocol connects a Human-approved browser identity to a local workbench. It does
not attest gameplay, enroll recordings, grant a campaign's upload consent, run a game or
change a Dataset. Cloudflare Access owns Human authentication. The Hub operations database
owns live project membership, device credentials, stable ownership, approval flows and personal
sessions. [ADR-0006](adr/0006-project-members-and-local-models.md) defines the current member/admin
design. This document describes current source; migration, deployed identity and new-member
Human usability require their own exact qualification before a release is recommended.
The local workbench keeps credentials outside browser JavaScript and calls these APIs.

## Three separate authorities

- Browser: Hub verifies the Access application JWT signature, issuer, audience, time, email
  and subject. Stable `principal.subject` is SHA256 of the JSON `[issuer, sub]` pair. Signed
  identity alone grants no project data. Current Hub membership grants `member` or `admin`.
- Device: a revocable credential belongs to one logical computer. It permits its delivery
  and receipt operations and explicitly allowed artifact access, not personal membership or
  another computer's evidence. Website logout does not revoke it.
- Personal local session: an opaque expiring token permits the current member's shared
  project views and supported member operations. It cannot upload recordings, grant itself
  administrator rights, impersonate a device heartbeat or make browser-admin mutations.

## Hub membership and first login

There are two Human console roles. Members can inspect shared project data, select explicitly
shareable exports, review research lineage and use supported local model workflows. Job
submission remains with existing CLI and budget controls; member API writes are limited to
explicit activity enrollment and export selection. Administrators additionally
manage members, device enrollment quotas and activity templates. Native control remains local
and separate. Membership grants neither sealed-test access nor unlimited compute.

An administrator adds an email in **成员管理**, with role, enrollment permission and device
quota. No invitation email is sent automatically; the administrator shares the project entry
through the project's ordinary channel. The invited member logs in using that email and a
verification code. The first verified browser request activates and binds the account profile;
creating a device is not required to see the profile. There is no separate project password or
open self-registration. Matching email cannot silently replace a previously bound provider subject.

Member requests revalidate current membership through the owning Operations service. Disabling
someone immediately rejects subsequent personal requests, clears personal sessions and revokes
owned devices. Re-enabling membership does not reactivate those credentials. Existing accepted
uploads and immutable records remain intact. Previously issued R2 grants may remain usable for
their bounded lifetime; revocation does not recall bytes already delivered. Last-active-admin
protection rejects disabling or demoting the final administrator.

Members see project metadata without becoming owners of other computers. Device filters select
a view; they grant no control. Existing imported claim scopes only allow a proved legacy device
binding. Administrator writes require a fresh browser Access session, exact Origin and CSRF,
plus live administrator authorization. A local personal token is never an admin credential.

For this candidate, configure the Cloudflare application with **Allow → Include → Login Methods → One-time PIN**, with OTP
enabled as an identity provider; there is no second per-email project roster. This deliberately
allows any email holder who completes OTP to reach Hub authentication: Hub must then reject
nonmembers on every protected route. Cloudflare recommends email/domain restrictions for
applications relying on Access alone, so this project-specific split is not that default policy.
Never use Bypass. See [common Access policies](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/common-policies/)
and [OTP setup](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/).
The exact edge change and negative origin checks are separate deployment gates in the
[Hub runbook](../deploy/hub/RUNBOOK.md#browser-console-login-and-local-connection).

The old `stpd/console-access-v1` file is archival/explicit migration input only.
`STPD_ACCESS_ALLOWLIST` is rejected in runtime configuration. It cannot grant or revive
membership. Current browser configuration uses only `STPD_ACCESS_ISSUER` and
`STPD_ACCESS_AUDIENCE`; no Cloudflare administration credential is installed in the Hub.

## Local connection flow

All times below are UTC RFC3339 strings. Flow IDs are 32 lowercase hexadecimal characters.
The local process generates at least 32 random URL-safe characters as `client_secret`, stores
it with the pending flow before opening the approval page, and never places it in a URL,
browser storage or a log. A lost creation response can leave an unapproved flow that expires;
no device or personal session exists until explicit browser approval.

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
New enrollment requires current `enroll_devices: true` and remaining `device_quota`; ownership
alone permits later reconnection to an active device. Project visibility does not grant this proof.

## Reads, logout and device observations

`GET /v1/identity/me` uses the personal Bearer token and returns the identity projection without
CSRF. `principal` includes subject/email, role, member ID/status, project/member-action flags,
device scopes, enrollment permission and quota. `devices` includes ID/name, active status, last
observation, ownership and permitted revocation. Missing observations are null, never assumed
current. Account email is private to its principal and authorized member administration; shared
device metadata does not expose another owner's email.

`GET /v1/identity/console/{overview|collections|collections/ID|datasets|datasets/ID|jobs|models|models/ID|system}`
uses the same safe `stpd/console-v1` projections as the browser. Both personal and browser
console reads accept `device=DEVICE_ID`, which must be a subset of the current principal's
project-visible computers; unknown/duplicate filters fail closed. Project members may view
shared metadata beyond personally owned devices. Filters do not grant ownership, raw payload
access or per-device research admission.

Personal sessions expire no later than 24 hours or the approving Access JWT, whichever is
earlier. Current membership, role and owned/shared scopes are evaluated on each read.
`POST /v1/identity/logout` deletes only that personal token and is idempotent. It does not
revoke a device, stop a local worker or sign out the separate browser Access session.

`GET /v1/identity/device` uses only a device credential and returns
`{device_id, name, active: true, last_seen, presence}`. A personal token cannot substitute.
`POST /v1/identity/device/heartbeat` accepts `{}` or `{version: STRING}` and records the
observation time, not a promised online state. Version is bounded metadata, not build proof.
The `/v1/*` delivery contract remains separate; artifact reads additionally follow the current
project-sharing/lineage policy. A device ID or known artifact ID cannot bypass sealed access.

## Bounds, maintenance and validation

Identity request bodies are at most 8 KiB for create and 1 KiB for approval/poll/heartbeat.
The Hub keeps at most 1,000 unexpired flow rows, 32 current personal sessions per Human and
at most the current member quota (default 3, maximum 128) owned devices per Human. Public creation
is limited to 20 requests/minute and polling/acknowledgement to 300/minute per actual socket source; all requests behind a single trusted
reverse proxy share its socket-source limit. Arbitrary forwarded IP headers never relax it.
Rate storage is bounded to 2,048 keys in the current minute. No public endpoint lists flows.

Operations schema 4 adds durable membership, enrollment scopes and collection activities to
the existing identity/operations store. Explicit `members-bootstrap` imports reviewed schema-3
identity configuration and names the administrator separately. Keep original subjects, device
IDs/owners/token hashes, uploads, receipts, jobs and audit records. Back up with the qualified
predecessor image before any new Operations command can migrate schema, then retain that exact
paused snapshot/image/private-config pair. Current backup/restore requires schema 4; old code
must not open the migrated live DB. See [migration and fresh-admin activation](../deploy/hub/RUNBOOK.md#migrate-schema-3-identities-to-hub-membership-schema-4).
Whole-host recovery includes the separately retained identity master key and deployment config.
A fresh explicit bootstrap's one-time pending-admin marker never substitutes for an existing
site's administrator. Browser activation clears it; preflight cannot manufacture that event.

`python -m stpd.hub rotate-device --device EXACT_DEVICE_ID` reads the replacement credential
only from `STPD_DEVICE_TOKEN`. This explicit operator operation replaces the credential hash,
restores device access, invalidates the old credential and appends an audit event, preserving
ownership and all old upload identities. It cannot repair an existing Platform outbox incident;
that owner's authentication-block/recovery protocol is separate. No direct SQLite edits or
transport-file deletion are supported recovery mechanisms.

Portable regressions exercise actual signed JWTs, expiry, origin/CSRF/replay, same-device proof,
account switching, concurrent approval, rollback, response-loss recovery, token confusion,
scope changes, logout, rate limits, member revocation, last-admin protection and legacy
schema/credential/upload preservation. They do
not establish real Access login, production TLS, terminal usability or Human-origin evidence.
