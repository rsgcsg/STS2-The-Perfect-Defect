# Portable identity repair, 2026-09-06

## Observed failures and owning repairs

The first complete Windows lane rejected the installed Host package while Linux passed.
`directory_sha256` sorted host Path objects, which use different case ordering on Windows.
Commit 8779b70b260f085a404a0a3c1b64f136ce5ee590 instead sorts canonical relative POSIX
strings and still hashes exact file bytes. Both hosted doctors then passed the same package
identity. No package pin, byte verification, or required check was weakened.

The complete suite subsequently exposed Windows logical-path separators in derived feature
binding and implicit CRLF translation in generated evidence. Repair e8ac8c9258ae41278819133b40fea1f183036673
uses PurePosixPath for logical identities and explicit LF text writers for staging, derived
feature artifacts, and synthetic V2 evidence fixtures. The Platform verifier remains unchanged.

The package verifier belongs to the live policy's reviewed runtime source closure. Its change
therefore legitimately invalidated the old code pin. Both policy manifests now bind
607b108f81cabc9721f9debd3d3a6c1e79f4e5a4bff8eba85308a2382fb74dfe and have new manifest IDs
ending in `-portable-607b108f81ca`. Their checkpoint/config/environment requirements are unchanged.
This is a new source candidate, not transferred runtime or Human qualification.

## Execution and evidence boundary

A one-shot workflow restricted to the owned governance topic branch performed only the
reviewed mechanical edits, checked its allowed file set, refused a concurrently moved head,
and pushed without force. It removed both its own workflow and script in the resulting
commit. No protected branch, ruleset, secret, raw Human bundle or Platform source was changed.

Earlier CI runs are retained failures: 34015822425 and 34016048855. The latter passed doctor,
Ruff, Mypy and SDK checks on both systems, then failed 2 Linux / 5 Windows tests. Those results
are diagnostic evidence, not a pass for this repaired candidate. Fresh latest-head Linux,
Windows, aggregate, package and patch-hygiene evidence is required after this report's commit.

The autonomous pre-Full-Run program remains incomplete. Artifact/registry/data/worker/model/
evaluation integration and final readiness have not been established by this repair.
