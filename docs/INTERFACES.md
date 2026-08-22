# Interfaces

Machine-readable companion schemas live under `schemas/`. Payload schemas are intentionally
versioned before model code depends on them.

## 1. Player Environment port

STPD consumes a strategy-free interface:

```python
reset(seed) -> stable Snapshot
observe() -> current Snapshot
read(read_id, snapshot_id) -> Read result
step(bound_action_id, snapshot_id, mutation_request_id) -> Receipt + successor
close() -> None
```

Requirements:

- the Snapshot contains a complete finite action catalog before STPD acts;
- `bound_action_id` is opaque, state-bound execution authority;
- unknown delivery is never retried;
- stale refusal causes a fresh observation and new selection, not replay;
- the successor is the next stable interactive state or terminal;
- Host/session/native identifiers never become model inputs.
- localized labels may be evidence/model text but cannot be the sole action
  identity or deterministic policy-ordering key.

An episode and every derived transition are environment-invalid after any
`unknown` delivery, incomplete catalog, settling timeout, missing successor,
replayed stale authority, mid-episode runtime/environment identity change,
request/action/Receipt mismatch, or unexpected environment exception. Invalid
data is quarantined; it is never silently retained for training.

Failure ownership starts with the same exact scenario: both Reference and
Managed failing points to Connector/game contract; Reference passing and
Managed failing points to Headless; both environments passing points to STPD.
Any identity change is a requalification event.

## 2. ResearchState v0

A deterministic player-visible object projected from one coherent Snapshot plus declared
Reads. It contains semantic facts needed for research and excludes:

- hidden draw order, private RNG, unrevealed content;
- runtime/process/session IDs;
- opaque action IDs except in local execution linkage;
- teacher/model identity or future outcome.

Every ResearchState records `schema`, `information_policy`, `game_version`, and a normalized
state hash. It is not yet frozen; Step 0 must freeze it before data collection scales.

## 3. ResearchAction and ModelAction v0

ResearchAction is a deterministic player-visible description of one legal candidate. It has
a dataset-local `action_key` derived from visible semantic content. The runtime
`bound_action_id` stays in an execution envelope and is never serialized into ModelAction.

ModelAction is the deterministic model-facing serialization of ResearchAction. Candidate
order is randomized or explicitly recorded for evaluation; localized display text cannot be
the sole identity or ordering key.

## 4. ModelState profiles

- `stpd-combat-v0-lite`: minimum combat facts required by the experiment.
- `stpd-combat-v0-standard`: default v0 profile and all core architecture runs.
- `stpd-combat-v0-full`: broader player-visible context for winner-only ablation.

Profiles change information volume and token cost, not legality or environment authority.
Serializers are deterministic and versioned.

## 5. ResearchTransition v0

Canonical shape:

```json
{
  "schema": "stpd/research-transition-v0",
  "transition_id": "...",
  "episode_id": "...",
  "step_index": 17,
  "seed": "...",
  "environment": {
    "game_version": "...",
    "game_commit": "...",
    "host_source_revision": "...",
    "host_artifact_sha256": "...",
    "connector_version": "...",
    "connector_artifact_sha256": "...",
    "information_policy_id": "player_visible_v1"
  },
  "policy": {
    "source": "strong_teacher",
    "version": "...",
    "teacher_confidence": 0.8
  },
  "input_profile": "stpd-combat-v0-standard",
  "eligibility": {
    "rank": true,
    "transition": true,
    "return": false
  },
  "state": {},
  "legal_actions": [],
  "chosen_action": {},
  "successor": {},
  "terminal": false,
  "outcome": null
}
```

Eligibility meanings:

- `rank`: the behavior source is eligible to supervise action ranking;
- `transition`: `(s, a, stable s')` is semantically reliable;
- `return`: the episode has a reliable terminal outcome.

Random/exploratory actions may be transition-eligible while rank-ineligible.

## 6. Qwen backend port

The v0 backend is pinned to `Qwen/Qwen3-0.6B-Base` and exposes:

```python
encode_joint(state_texts, action_texts) -> pooled hidden states
encode_state(state_texts, return_sequence=True) -> hidden sequence + mask
embed_action_tokens(action_texts) -> frozen token embeddings + mask
identity -> model/tokenizer revision, dtype, device, frozen flag
```

Generation/chat APIs are not part of the core v0 interface.

## 7. ActionScorer

```python
score(model_state, model_actions) -> one scalar per legal action
```

The scorer must preserve candidate count and order. Selection happens outside the model by
`argmax` over the current complete action set.

## 8. Experiment and artifact manifests

`experiment-manifest-v0` binds source, plan, data manifests, Host/Connector/Qwen identities,
architecture/config, seeds, benchmark set, and output locations.

`model-artifact-manifest-v0` binds a frozen checkpoint to the experiment, files/checksums,
data manifests, metrics, compatibility scope, and non-claims.
