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
