# Current local policy package binding

The reviewed registry is `configs/developer/local-policies-v1.json`. Its optional
Runtime package is independent of the collector installation. It pins
`@rsgcsg/sts2-policy-runtime@0.1.0-rc.2`, the release archive SHA-256, installed
package content, component source/tree revisions, and the installed zod content.
The Connector package retains the exact public pin in `combination-v1.json`.
Install checks the archive before npm, disables lifecycle scripts and user/global
npm credentials, and validates the installed Runtime and dependency bytes before
promoting the private directory. Readiness repeats the content checks and calls
the installed public `validatePolicyManifest` decoder without loading a model.

The current S1 selection is `s1-human-combat-v4`. Its v4 manifest corrects a G2
STPD-owned public contract mismatch: historical v2/v3 placed `code_digest_scope`
inside the strict Platform adapter identity. The public manifest, NDJSON startup
attestation and evidence verifier accept only `id`, `version`, `protocol` and
`code_sha256` there. V4 places the STPD scope in `adapter_config.s1` and binds a
new adapter source digest. Historical manifests remain unchanged and are not
silently migrated. The matching adapter defaults are v4 and
`configs/v0/experiments/s1-human-combat-live-v2.json`.

The checkpoint, Qwen, serializer, empty model Read policy, complete candidate
ordering, Defect A0 combat admission and exact native environment requirements
are unchanged. Existing historical weights, READY and checkpoint identity files
must already be present with their exact hashes, and this adapter requires CUDA
BF16. Runtime installation, static readiness and actual model loading are separate
states. The service starts in Human mode and does not infer current game
compatibility from a package install. Full-Run `stpd/scheme1-model-v1` downloads
remain incompatible: they lack a registered live inference adapter and proven
training/live input parity.

The portable regression checks the current manifest, frozen policy preservation,
scope/identity rejection, candidate order and uncertain-request behavior. The
optional exact-package gate additionally consumes actual Python adapter startup
output with the public `NdjsonPolicyPort` and verifies public-package sealed
evidence with the pinned Python Evidence verifier:

```sh
STPD_TEST_POLICY_RUNTIME_NODE_MODULES=/absolute/private/state/models/runtime/node_modules \
  uv run --locked python -m pytest -q -p no:cacheprovider tests/test_policy_adapter.py
```

This gate uses a synthetic CPU scorer and a stopped-only evidence fixture. It
does not load trained weights, play the game, measure model quality, qualify a
native runtime, admit training data or transfer prior Human evidence. Runtime
operation handoffs report verified operational event/delivery counts, with game
outcome unmeasured. Rollback uses the previous source and its matched historical
manifest/configuration; it does not relabel previous evidence as v4 evidence.
