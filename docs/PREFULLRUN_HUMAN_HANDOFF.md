# Pre-Full-Run Human and external-input handoff

Engineering operations require no source edits. Exact qualified-source evidence is attached
to the final develop commit in `refs/notes/stpd-prefullrun`; see
[AI closeout](PREFULLRUN_AI_CLOSEOUT.md). Use the supported bootstrap and commands in
[PREFULLRUN_OPERATIONS](PREFULLRUN_OPERATIONS.md).

## Object storage account

Provision an S3-compatible bucket/prefix, configure endpoint/bucket/prefix/region through
`STPD_S3_*` environment variables, and supply scoped SDK credentials through the environment
provider. Do not send, commit or paste credentials into manifests or launch packets.

```bash
uv run --locked python -m stpd.workbench doctor --store s3 --smoke
```

Retain its actual provider result as separate qualification. It tests conditional writes,
idempotence/conflict rejection and readback with an isolated retained probe. Fake S3 CI is
not real account qualification. The core has no R2/AWS/other vendor branch.

## Disposable GPU account

Choose a Linux GPU provider and provision the device required by the frozen config. Push the
exact prepared Run lineage, generate the launch packet and execute its commands on the new
host with scoped storage credentials. The packet pins Git SHA, uv.lock and exact Worker Run.

```bash
uv run --locked python -m stpd.workbench push --artifact <run-id> --other-store s3
uv run --locked python -m stpd.workbench launch --run <run-id> --output .local/launch.json
```

Use the same worker protocol on every provider. Recovery explicitly names the exact durable
checkpoint; workers cannot select a different dataset/config. Provisioning does not authorize
a scientific campaign. Real Qwen snapshot/CUDA/BF16 admission retains the existing exact pins.

## Final Platform re-entry

Platform must supply its final qualified Full-Run bundle/schema after mandatory surface census,
source freeze, exact build/install/load, Human canary, continuous natural Full Run and
occurrence/disposition audit. STPD does not reconstruct these facts from public bindings.

That external delivery opens the next narrow integration phase: exact final adapter, real
corpus validation, candidate/token profiling, final Standard serializer freeze, canonical
Full-Run Dataset, Gold population and scientific protocol freeze. Those depend on unknown
final Platform bytes and are not unfinished Pre-Full-Run architecture work.

## Human Gold

After qualified data exists, use `python -m stpd.fullrun.gold_cli` (under `uv run --locked`) to
prepare Gold-dev/test tasks and export their blank annotation templates. Humans provide real
acceptable action sets, optional best action and invalid/insufficient-information dispositions.
Import the filled annotations with `labels`; use `report` for coverage. Collection never
copies observed teacher choices into Gold labels. Engineering fixtures remain synthetic.
Gold-test tuning is rejected and its evaluation requires an exact frozen protocol/model.
See [Gold operations](FULLRUN_GOLD.md).

## Scientific and live execution

Only after data/Gold/protocol freeze run the real GPU campaign and sealed evaluation. Real
STS2 live evaluation additionally requires qualified Platform runtime and Human operation.
The E0–E7 engineering configuration defers dynamics and scientific/live promotion; it does
not invent final experiments or labels. Existing combat-v0/S1 evidence is not Full-Run proof.

No claims: real Full-Run corpus, real Human Gold, cloud qualification, Qwen advantage,
scientific model quality, completed campaign or successful live STS2 evaluation.
