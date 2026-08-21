# Code and Style Guide

## Language baseline

- Python 3.9 or newer, UTF-8, LF endings.
- Four-space indentation and a target line length of 100 characters.
- Public functions, classes, dataclasses, and protocol methods use type hints.
- `from __future__ import annotations` is preferred in new modules.

`.editorconfig` carries the editor-neutral formatting baseline. A formatter/linter becomes a
required gate only after it is added to the development dependencies and the existing tree
passes it; documentation must not claim an unconfigured gate.

## Design rules

- Prefer small modules with one owner: environment, data, representation, model, training,
  evaluation, experiment, or qualification.
- Use `Protocol` at external boundaries, `dataclass(frozen=True)` for immutable identities,
  and `TypedDict`/schemas for serialized records.
- Avoid inheritance when composition or a small protocol is sufficient.
- Avoid generic `utils.py`; name modules after the responsibility they own.
- Do not create empty abstraction layers before a second concrete use exists.
- Configuration is explicit; no hidden global seed, device, dtype, path, or model revision.

## Determinism and errors

- Derive and record Python, framework, data-loader, and experiment seeds.
- Sort or preserve candidate ordering intentionally; never depend on localized labels.
- Hash manifests and artifacts using stable canonical serialization.
- Fail closed on incomplete action sets, identity drift, unknown outcomes, schema mismatch,
  future leakage, and missing provenance.
- Errors should name stage, identity, expected condition, and available recovery.

## Logging and evidence

- Use structured records for experiments and machine checks.
- Human logs explain progress; machine reports carry verdicts.
- Never write secrets, raw save data, Steam identifiers, private paths, or full external
  examples into committed reports.
- Distinguish `implemented`, `tested`, `runtime_measured`, `qualified`, and `inferred`.

## Testing

- Pure unit tests must work without STS2, Headless, Connector binaries, Qwen weights, GPU,
  or network.
- Contract tests cover positive and fail-closed negative paths.
- Data tests cover leakage, deduplication, split isolation, and provenance.
- Model tests use tiny deterministic fixtures and verify candidate-score alignment.
- Runtime and GPU experiments are separate evidence commands, not unit tests.

## Model code

- Model forward paths consume typed ModelState/ModelAction batches, not raw Connector JSON.
- Qwen access goes through the pinned backend port.
- Scheme-specific code owns only its architecture; common data/evaluation code is shared.
- Checkpoints include config, source/data/model identities, and optimizer state where needed.
- A cached forward pass and a cold forward pass are reported separately.
