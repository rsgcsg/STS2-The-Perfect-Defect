# ADR-0003: Local-First manifest research boundaries

Status: accepted architecture; implementation/evidence is reported separately.
Date: 2026-09-06

## Decision

GitHub owns exact source. Local machines own research control, interactive analysis and real
STS2 operation. Object Store holds durable bytes and immutable manifests. SQLite is a
rebuildable local metadata projection; DuckDB is local analysis. Cloud machines are disposable
workers for feature computation, training and offline evaluation, not game authority. V1
requires no persistent server, production Postgres, central job queue or public dashboard.

Platform owns native legality, semantic S, complete A_sem(S), Commit, causal successor,
Human/native correlation and qualification. STPD owns research projection and science.
H is not S; public action bindings are not the authoritative semantic catalog. Historical
combat-v0 remains unchanged; Full-Run representation and protocols are separately versioned.

## Stable identities and replaceable mechanisms

Typed Producer, Parent, Payload and Manifest contracts bind exact source and uv.lock, parent
IDs, roles, content SHA-256, sizes and versioned parameters. Manifest ID is a hash of canonical
semantic content. Filesystem paths, bucket names, GPU providers and database primary-key
allocation are not domain identity. The manifest is published only after every payload has
been verified and referenced parents exist. Readers verify canonical bytes, IDs and payloads.

ArtifactStore is independent of S3 and local files. Its bounded immutable blob adapters use
conditional no-overwrite publication. Payloads are streamed in canonical 8 MiB chunks, with
an immutable transport index. Domain payload identity is the full-byte hash and size, not
chunk layout or vendor metadata. An S3 ETag is never treated as SHA-256. Unsupported conditional
writes fail closed, rather than falling back to an unsafe overwrite. Local publication uses
fsynced temporary files and atomic hard links. This is not a claim of filesystem power-loss
qualification on every platform.

Registry is an interface; SQLite is one implementation. A rebuild validates all manifests
and lineage before replacing the index transactionally. A corrupted or deleted cache does
not destroy an identity. Sync discovers manifests and fetches parent metadata without requiring
large payload download. Research/training code must not import SQLite, boto3 or a web framework.

RunReporter will expose immutable events/checkpoints/results. A future Research Hub can replace
Registry and RunReporter adapters without changing Dataset, TrainingInput, Run, Model or
Evaluation identity. Store changes alter configuration/adapters only; GPU changes alter the
launcher only. All providers execute the same verified worker input and CLI.

## Deliberate refinements of the task sketches

The existing `stpd/artifacts.py` and `stpd/representation.py` are retained; new contracts and
adapters use separate namespaces rather than breaking historical imports for directory style.

Manifest identity excludes wall-clock time. Publication/run event records carry operational
timestamps separately, so re-publishing identical content remains idempotent and vendor moves
do not manufacture new research objects. A timestamp is neither scientific identity nor proof
of a latest/final result. No mutable status file is the only durable run truth.

The portable storage layer uses bounded chunks rather than requiring multi-gigabyte objects
in RAM or relying on vendor-specific multipart completion semantics. Current publication
re-verifies payload bytes for correctness; throughput is measurable and not presumed optimal.

## Security and evidence

Credentials come from a scoped SDK provider chain, not manifests, packets, repository files
or dashboard HTML. HTTPS is required except explicit loopback development endpoints. Object
keys are portable and traversal-safe. Writes reject existing different bytes; no delete/GC or
credential provisioning is implied by the store interface.

Local/fake/S3-stub conformance is engineering evidence, not production S3 qualification.
Fixture training does not prove pretrained-Qwen value, Human quality, scientific performance
or real STS2 capability. The final Platform adapter and Standard serializer freeze wait for
qualified real bundles and actual profiling. Readiness must be supported by latest source,
Linux/Windows CI and a complete fixture E2E, not this ADR.
