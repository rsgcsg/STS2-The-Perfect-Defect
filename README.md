# STPD Training Smoke

This local research consumer tests whether a real external learner can consume
the STS2 Player Environment. It is intentionally independent from
STS2-headless and STS2-Connector: those projects own Host/gameplay truth, while
this project owns feature projection, shaped reward, learning and evaluation.

The current model is a small linear Q learner used only for H1 integration and
resource evidence. It is not the planned Qwen STPD model and makes no claim of
optimal play or calibrated win probability.

```bash
PYTHONPATH=../STS2-headless/consumers/python:. python3 -m stpd.training_smoke \
  --headless ../STS2-headless \
  --candidate ../STS2-headless/.local/candidates/<exact-candidate>
```

The run records candidate provenance, transition throughput, learner cost,
training curves, a frozen model and fixed-seed random-versus-trained
evaluation. Candidate-to-Reference evaluation is a separate gate.

## Multi-seed contention smoke

The contention smoke is a separate integration check for a shared Python
learner with multiple independent environment actors. It uses one
`ManagedPlayerEnvironment` per worker and the strategy-free
`ThreadedVectorPlayerEnvironment` adapter from `STS2-headless`; it does not
add STPD semantics to either host. Each worker has its own runtime instance,
while learner updates are serialized through one explicit lock.

The command below starts real candidates and is therefore not part of the
pure-Python test suite:

```bash
PYTHONPATH=../STS2-headless/consumers/python:. python3 -m stpd.contention_smoke \
  --headless ../STS2-headless \
  --candidate ../STS2-headless/.local/candidates/<exact-candidate> \
  --workers 2 \
  --training-seed STPDSEED01 \
  --training-seed STPDSEED02
```

The report fails closed when identity is incomplete/inconsistent, any
worker does not reach `game_over`, a delivery becomes unknown/failed, seed or
worker coverage is incomplete, or learner-update parity is lost. A passing
report is still only an integration/contention smoke: it is not H1 admission,
Reference transfer, reliability qualification, or a learning result.

Pure tests do not import the Headless package or launch a candidate:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q stpd tests
```
