# ADR-0004: Developer cloud Hub and immutable execution

Status: accepted for B pipeline implementation; runtime qualification is separate.

The user-selected B design evolves ADR-0003's local-only control placement. Keep public
artifact identities and the local CLI. Add one small hosted application composed from the
same research services, with an independently durable operational database.

The operational database owns device authorizations, upload state, task attempts/leases,
budget reservations, cancellations and administrative audit events. It is not the existing
rebuildable Registry. It requires consistent backups; restoration starts paused and reconciles
external work before scheduling. ArtifactStore continues to own immutable bytes/manifests.

Uploads use isolated staging and a Platform transfer manifest. A client may never publish
trusted evidence directly. The receiver verifies archive bounds/hash, exact file inventory
and the pinned Platform verifier before publishing a receipt. Transport receipt is separate
from research admission. Failed evidence remains inspectable under authorized access.

Close-based transfer is outside the native game causal kernel. Only durable successful close
facts enroll normal sessions. Process restart reconciliation and upload retries do not infer
game successors or retry gameplay. Tool identity is release-bound rather than a mutable
developer checkout. Human attestation must be supplied explicitly by the operator.

CPU control prepares immutable feature-job input. Disposable compute produces features before
TrainingInput/Run creation. Provider adapters invoke the existing worker; no provider-specific
training semantics. Provider submission uncertainty is reconciled, not blindly resubmitted.
An expired lease does not prove a worker stopped. Attempts fence final selection; candidate
artifacts from older attempts are preserved but cannot become the current selected result.

The initial application is for a small known developer group, with scoped revocable tokens,
private storage, one automatic GPU job and explicit launch budgets. No public multi-tenancy,
new models, scientific campaign, cloud gameplay, RL or inference service is admitted here.

Cloud deployment follows exact image/config, staging, bounded integration, failure/recovery
tests and rollback. Account setup/billing, unavailable credentials, actual Human play and
required independent approvals remain owner actions. Existing credentials/authorizations
are reused without repetitive confirmation.
