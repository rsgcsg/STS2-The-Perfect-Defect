# Exact-source disposable compute

The Hub owns queue, attempt, lease/fence, budget and final selection. This adapter only runs
existing STPD code and returns a candidate. It does not provision accounts or qualify a GPU.
The portable tests never deploy an App, fetch weights or use paid compute.

## Input and output

A CPU controller publishes `FeatureJobSpec` + `publish_feature_job` against an already
validated ModelView. Supply the exact target Qwen identity, hidden size, batch size, fixed
TrainingConfig and optional protocol. The Qwen identity comes from the qualified target
image/backend, not the CPU controller's installed torch version. Preparing the job never
loads Qwen. Real pretrained and admitted random identities both retain the existing pin.

Call `dispatch(store, ComputeRequest('features', ...), runtime, backend=...)`. It uses the
existing feature compiler, rejects Qwen/dimension/source drift before encoding, and returns
a `ComputeReceipt`. `validate_receipt` checks binding and immutable payload/lineage on CPU.
Then `prepare_feature_run` freezes the existing TrainingInput/Experiment/Run contracts.
Dispatch `ComputeRequest('training', run_id, ..., resume=exact_checkpoint_id)` with no model
backend: training uses only the frozen FeatureSet. An explicit stop budget yields a paused
receipt; otherwise the existing Worker publishes model, dev evaluations and RunResult.

Receipts are **candidate_prepared**, not Hub completion or scientific admission. The default
CandidateReporter writes immutable events/candidates, including compute attempt/request
references in event details, and never writes `run-completions/`. Hub must persist requests,
validate receipt identity and payloads, then select results in its current fenced transaction.
CPU receipt checks are binding/integrity checks, not a GPU replay or model-quality verdict.
Interrupted feature compilation can be explicitly rerun; there is no fabricated partial
FeatureSet or implicit "latest" checkpoint. Training resumes only an explicit same-Run ID.

## Image and deployment

1. Push/review the exact source candidate and resolve its Producer and lock hash.
2. Build `Dockerfile` with `BASE_IMAGE` set to a Python 3.11 Debian registry reference **by
   digest**, and `STPD_SOURCE_REVISION` set to the full reviewed commit. No floating base
   image belongs in a deployment receipt. The image retains that clean checkout and runs
   `uv sync --locked --all-extras`; no local source or credentials are copied into it.
3. Push the built image and resolve its immutable registry digest. Capture build source,
   base image, uv version, final OCI digest and registry/build receipts separately.
4. Create a `ModalTarget` JSON using the Producer, final image `@sha256:...`, explicit GPU
   (or `none` for CPU), timeout, named storage Secret and optional pre-existing Qwen volume.
   The Secret contains scoped `STPD_S3_*` / `AWS_*` environment settings, and when required
   `STPD_QWEN_SNAPSHOT` points at a pre-verified snapshot under `/qwen`. Never put values in
   JSON. Worker credentials must not grant Hub database, deployment or final-selection access.
5. Set `STPD_MODAL_TARGET` to that file and deploy using the locked `cloud` extra:
   `uv run --locked --extra cloud modal deploy deploy/cloud-worker/modal_app.py`.
6. Keep the exact target JSON and returned deployment/image identity as service evidence.
   Account/region/device qualification and cold GPU source/lock/backend identity are separate
   real-runtime gates; a successfully built definition is not qualification.

One app name is derived from the complete target hash, including source, OCI digest and
resources. Modal's free/default lookup routes to a named App's latest version; do not redeploy
changed code/resources under an old target name. Each invocation verifies target ID and the
worker verifies actual clean executing-checkout Producer. It invokes the image's locked
`/opt/stpd/.venv/bin/python -m stpd.cloud_jobs`, not Modal's injected SDK Python for training.
No source-identity check is disabled to support packaging. The wrapper is serialized with
only standard-library dependencies and primitive target identity, not the local STPD package.

## Submit, reconcile and restore

Persist `submitting` plus the request/target/attempt before calling `ModalProvider.submit`.
Persist the returned ModalCall before reporting submitted. SDK errors during submit mean
`submission_unknown`: the remote invocation might exist. There is no automatic retry, and
provider inspection/terminal reconciliation is required before a new attempt. `poll` is
non-blocking and receipt-bound; timeout only means no result yet, not proof of worker health.
`cancel` requests cancellation but does not manufacture a terminal result. Keep the call ID
for operator reconciliation if the provider reports an ambiguous cancellation or result.

Modal worker settings are one container, zero warm containers, a fixed timeout and zero
user-code retries. Infrastructure preemption or client-level delivery behavior can still
cause duplicate execution; fencing is always required. Scoped immutable candidate writes are
safe to retain; the Hub must never interpret their mere existence as final selection.

Official API references checked for this implementation:
- https://modal.com/docs/guide/trigger-deployed-functions
- https://modal.com/docs/reference/modal.FunctionCall
- https://modal.com/docs/guide/images
- https://modal.com/docs/guide/retries

Provider adapter tests plus CPU replacement-process evidence qualify only engineering.
They do not establish account availability, real S3 semantics, CUDA/BF16 admission, cost,
scientific validity, Human origin or native gameplay correctness.
