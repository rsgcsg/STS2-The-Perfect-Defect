# Code and Style Guide

## Language and tooling

Python >=3.11,<3.12, UTF-8, LF, four spaces, target line length 100. pyproject.toml and
uv.lock are machine authority. Ruff and Mypy are required through the common repository gate;
use Pytest, compileall and package build as documented in [Testing](TESTING.md).
No formatter/linter churn without a demonstrated need. .editorconfig configures editors;
.gitattributes controls checkout text bytes across operating systems.

## Ownership and interfaces

One module owns one class of fact. Prefer typed public functions, dataclass(frozen=True),
explicit JSON codecs and small Protocols. Compose rather than inherit when simpler. No
arbitrary dictionaries as unvalidated durable contracts, generic utils dumping grounds,
module-level mutable experiment state or cosmetic directory migrations.

Research, data, representation, Qwen, model, training, evaluation and peripheral mechanisms
remain distinct. Core code does not import a storage SDK, SQLite, web framework or cloud
provider. Adapters depend inward. Dashboard/Registry/analysis are projections, not scientific
admission authorities. Platform legality and causality never migrate into this repository.

## Determinism, leakage and failures

Explicitly bind source, uv.lock, Dataset, Qwen/tokenizer, serializer, candidate alignment,
configuration, seeds, device and dtype. Preserve semantic ordering where meaningful; never
use candidate position as a label feature. Manifest canonicalization and byte hashes are
versioned contracts. Durable object changes produce new identities, not silent overwrites.

Classify errors by stage, identity, expected/observed condition and recovery. Reject missing
provenance, unknown schema, incomplete catalogs, cross-split leakage, tampering and identity
drift. Never replace an unknown result with guessed success. Failures need regression tests.

## Model and evidence

Models consume admitted model views, not raw Connector JSON. Qwen goes through its exact
pinned backend; the first Full-Run Scheme1 scorer is shared across surfaces. Metadata can
stratify reports without selecting scene-specific heads. Frozen backbone gradients remain
absent. Checkpoints bind model/optimizer/input/config identities and resume state.

Use deterministic tiny/FakeQwen fixtures in CI. Report cold and cached performance separately.
Structured reports carry actual evidence; human logs explain it. Secrets, private paths,
identifiers, raw saves, weights and full external examples never enter committed reports.
Engineering, data, training, evaluation, service and scientific claims are independent.
