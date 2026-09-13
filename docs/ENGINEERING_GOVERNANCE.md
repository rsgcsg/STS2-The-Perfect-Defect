# STPD Engineering Governance V2

## Authority before implementation

Identify the owning fact before changing code. STS2/Host and Platform own legality, native
execution/Commit, Human/native correlation, semantic S, authoritative complete A_sem(S), and
causal successor. STPD consumes qualified evidence; H is not S and public bindings are not
the semantic legal catalog. No latest/FIFO/timer guess or second legality engine is allowed.

STPD owns research projection, admission, datasets, representation, models, training,
evaluation and scientific provenance. Object stores, registries, dashboards, analysis
engines and GPU providers are replaceable mechanisms, never scientific authority.

## Independent sources of truth

Source: exact commit, contracts, schemas, lock and tests. Data: source evidence, admission,
canonical/split manifests and hashes. Model: architecture/config, checkpoint hash and input
lineage. Training: verified input, execution and checkpoint evidence. Evaluation: exact
model/data/protocol and metric artifacts. Scientific: frozen protocol, sealed evaluation,
statistics and reviewed interpretation. Service: deployed digest, configuration and observed
runtime. No dimension automatically promotes another. Conversation intent can change a goal,
not prove an implementation. Current owning source/evidence overrides dated task sketches.

## Change and failure discipline

Prefer the smallest clean causal change, not the smallest textual diff. Fix a broken owner
and its consumers instead of accumulating compatibility guesses. Preserve historical
contracts unless a versioned migration explicitly replaces them. Reversible, bounded spikes
are allowed; delete unsuccessful approaches. No aesthetic mass moves or generic utils layer.

Classify impact: G0 governance/tooling; G1 owner-local behavior; G2 contracts/identities;
G3 model/training/evaluation semantics; G4 admitted artifacts/data; G5 real scientific/runtime
campaign; G6 production service promotion. Risk is causal, not line count.

Use the cheapest falsifying test, then owner tests and the complete portable gate. Add tests
for failure, tamper, concurrency, cancellation, recovery, stale identity and publication
ordering where applicable. A failure is work to repair, never permission to reduce the gate.

## Review, Git and agents

Review necessity, ownership, duplicated authority, failure model, test strength, identity and
claims before style. One lead owns integration/evidence; one worktree/branch per writer.
Worker output is a claim to verify, not acceptance evidence. Cross-layer changes require a
fresh review of the actual diff and repair of real causal defects before merge.

Fetch/prune and resolve exact develop/open PR topology. Use coherent topic PRs with exact
base/head, owner, failure model, impact, actual evidence, rollback and non-claims. Squash is
normal for STPD topics; unlike source tests, source-bound runtime/scientific evidence cannot
be presumed to transfer. Follow current rulesets, latest-head checks and resolved threads.
No admin bypass, protected direct push, force update or unapproved destructive action.

## Local-First target

GitHub owns source; Local owns developer control and real-world execution; generic S3-compatible
Object Store holds durable bytes/manifests. Registry SQLite and DuckDB are rebuildable views.
The B developer Hub adds a separate authoritative operations SQLite for device access,
uploads, jobs and attempts; it requires consistent backups and must never be rebuilt from
Registry. One CPU Hub coordinates disposable cloud workers without redefining
Dataset/TrainingInput/Run/Model/Evaluation identities. See [ADR-0004](adr/0004-developer-cloud-hub.md).
Service promotion requires exact deployment evidence; portable tests do not provision or
qualify it. Production Postgres, cloud STS2 and a public multitenant dashboard remain outside B.

Secrets, proprietary files, raw/private Human data, weights and large artifacts stay outside
Git and manifests. Scope credentials narrowly. Publication must be immutable, integrity-
checked and recoverable. Dashboard state is never an admission or scientific verdict.

## Done means evidence

Complete implemented contracts, real failure tests, current docs and latest-head required
CI; report remaining gates explicitly. Full-Run source qualification, final adapter/schema,
real-corpus profiling, Human Gold and live scientific evaluation remain separate from
synthetic engineering. Never declare readiness because a plan or checklist is complete.
