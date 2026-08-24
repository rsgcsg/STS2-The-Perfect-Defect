# Architecture

## Goal

STPD is a research system for learning and evaluating action scores over the complete
finite legal action set supplied by the Player Environment:

```text
Q_theta(state, action) -> scalar score
argmax over current A(state) -> selected action
```

In v0 the score is an action-ranking score, not automatically a calibrated win probability
or optimal Q-value.

## Dependency direction

```text
STS2 game truth
      |
Host: shipped Reference or qualified Platform Host Runtime
      |
Platform Connector / Player Environment
      |
STPD environment port
      |
ResearchState / ResearchAction / ResearchTransition
      |
ModelState / ModelAction serialization
      |
Qwen backend and model architectures
      |
training and evaluation
```

Dependencies flow downward. Model/training code may not import Host Runtime or Connector
source internals. Environment adapters consume immutable Platform packages and their public
contract; candidate and loaded-runtime identities remain separate.

## Ownership table

| Layer | Owns | Must not own |
|---|---|---|
| STS2/Host | game transition, RNG, effects, stable successor, runtime identity | research labels or model policy |
| Platform Connector | fair-player Snapshot/Read, finite BoundAction, Receipt, stale/idempotency | reward, tensor, Qwen/model APIs |
| STPD environment | transport adaptation and coherence checks | legality, native operands, business completion |
| STPD data | projection, eligibility, provenance, splits, manifests | hidden facts or anonymous mixed-source data |
| representation | deterministic ModelState/Action and Qwen input | environment mutation |
| model | scores and latent dynamics | data collection or evaluation policy |
| training | losses, sampling, optimizer, checkpoints | benchmark test-set mutation |
| evaluation | B0-B7 metrics, paired suites, statistics | training-time tuning on final test sets |

## Target source layout

The current smoke modules stay in place until a compatibility-preserving migration is
worthwhile. New production code should follow this layout when the first real module lands:

```text
stpd/
  contracts.py              typed cross-layer ports
  environment/              Player Environment adapters only
  data/                     ingestion, normalization, manifests, splits
  representation/           ResearchState/ModelState/ModelAction, tokenization
  qwen/                     pinned backend and cache management
  models/
    scheme1/                direct joint scoring
    simple/                 single-vector latent transition
    sdt/                    world-token dynamics transformer
  training/                 ranking, successor, anchor, later RL losses
  evaluation/               B0-B7 benchmark implementations
  experiments/              manifests, run orchestration, artifact registry
  qualification/            eventual home of current smoke lane
```

Do not create empty framework packages merely to match this diagram. Introduce a package
when its first tested responsibility is implemented.

Within `stpd/data`, `human_annotator.py` is the only strict native-human record
normalizer. `human_corpus.py` composes it across immutable session bundles and
owns registry validation, global collisions, whole-run/duplicate-component
splits, corpus identity, B0/profile reports and smoke handoff. It does not copy
or weaken Recorder mapping rules.

## Core abstractions

### PlayerEnvironmentPort

A strategy-free reset/observe/read/step/close interface. It returns stable observations,
complete finite actions, and Receipts. It never returns model tensors.

### ResearchState and ResearchAction

Player-visible, deterministic, versioned research objects. Runtime-local IDs are used only
for immediate environment execution and are removed before dataset/model boundaries.

### ModelState and ModelAction

Deterministic serialization profiles. Lite/Standard/Full change visible information volume,
not game truth or legality.

### QwenBackend

A pinned adapter exposing frozen state/joint encodings and action token embeddings. Model
architectures depend on this port rather than on `transformers` objects.

### ActionScorer

Consumes one ModelState and its current candidate ModelActions and returns one score per
candidate. It cannot invent or remove legal actions.

## Current smoke lane

The linear-Q learner is intentionally simpler than v0. It exercises:

- external environment consumption;
- `(state, actions, chosen action, successor)` flow;
- learning and frozen-policy serialization;
- multi-actor contention;
- Candidate-to-Reference execution.

It is a qualification baseline and future regression test, not a discarded dead end.
The pre-training environment smoke is deliberately cheaper than full
qualification and rejects incomplete authority, unknown delivery, missing
successor, provenance/identity drift and Receipt mismatch.

## Failure policy

- Missing/incomplete action catalog: fail closed.
- Unknown delivery: never retry the mutation.
- Stale snapshot with explicit fresh successor: observe/reselect; never replay old authority.
- Identity/schema/model/data drift: invalidate the affected cache/evidence.
- Unknown external data rights or provenance: exclude from training.
- Final-test leakage: invalidate the experiment, not merely the metric.
