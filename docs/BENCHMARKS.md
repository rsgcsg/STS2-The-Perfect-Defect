# B0-B7 Benchmark Tooling

The benchmark ladder separates evidence mechanics from scientific results. Implemented
functions can produce or reject reports, but an empty tool or synthetic fixture is never a
benchmark pass.

| Gate | Implemented mechanics | Still requires real evidence |
|---|---|---|
| B0 | schemas, leakage, catalog/successor/lifecycle, split/dedup and manifest checks | representative admitted datasets |
| B1 | Top-1, MRR, listwise NLL, pairwise and per-source ranking metrics | held-out behavior data and declared controls |
| B2 | best/acceptable labels, confidence, ambiguity, candidate permutation, sealed test and double-label agreement | human annotations and Gold sealing procedure |
| B3 | state-path masks and candidate-order shuffles without changing authority | predeclared intervention matrix and model outputs |
| B4 | normalized successor/ASR retrieval, rank/margin and collapse variance | real model embeddings and stable successors |
| B5 | source/Host/version/surface/action/metric stratification | current-patch and Managed/Reference runs |
| B6 | required-policy fixed-seed pairing, missing/unknown/pipeline-failure accounting | teacher and frozen winner journeys |
| B7 | profile/family/cold-cache token, action, latency, VRAM and cache distributions | measured CPU/GPU runs |

The current implementation lives in `stpd.evaluation`. It does not assign strategy labels,
impute missing policies, turn unknown delivery into a loss, or collapse different transfer
boundaries into one aggregate. Gold-test use fails unless the caller explicitly marks the
set sealed.

Synthetic tests prove deterministic report behavior only. They are not B1-B7 scientific
results and do not satisfy any promotion gate.
