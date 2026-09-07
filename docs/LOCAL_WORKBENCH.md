# Local Workbench

The local workbench is a read-only projection over the existing
`ArtifactStore` and `Registry` interfaces. It keeps local exploration close to
the immutable manifest and payload contracts while avoiding a server, a
database-backed authority, or a second evaluation implementation.

```python
from stpd.workbench.analysis import analyze
from stpd.workbench.dashboard import project, render_html

report = analyze(registry, store, duckdb_path=".local/workbench.duckdb")
dashboard = project(registry, store, analysis=report)
print(dashboard.to_json())
html = render_html(dashboard)
```

The two positional arguments are accepted in either order for small local
scripts (`analyze(store, registry)` also works), but callers should prefer
`(registry, store)` in new code. `artifact_ids=` narrows analysis to explicit
offline-evaluation manifest identities. DuckDB is used for bounded grouping of
evaluation rows; a database path is an optional local query cache and is never
included in the projection.

Analysis includes decision, surface, family, candidate-count, and serialized
text token distributions, plus Top-1, MRR, NLL, margin, and ten-bin ECE. It
also reports baseline/ablation rows and dataset record/run amounts. Token
counts are explicitly `whitespace-v1` exploratory counts, not Qwen tokenizer
measurements.

Latency, VRAM, throughput, and GPU-hours are read only from explicitly
recorded `performance`, `run_event`, or `run_result` manifest parameters.
When no value exists the field is `{ "status": "absent", "value": null,
"reason": ... }`; elapsed time, payload size, CPU type, or loss is never used
as a substitute. Failure events preserve an absent stage when the worker did
not record one.

`DashboardProjection` has the fixed sections Overview, Datasets, Experiments,
Runs, Models, Evaluations, Analysis, Lineage, Artifacts, and System Readiness.
It uses artifact identities, manifest metadata, parent edges, payload
descriptors, and registry cache state. It does not scan filenames or emit
private local paths. `render_html` produces a self-contained escaped static
HTML document with no server or external assets. System Readiness describes
only projection construction; it is not a data-admission, model-quality, or
runtime-qualification verdict.

The workbench is intended for local fixture and operator use. The canonical
artifact, evaluation, training, and scientific evidence contracts remain the
source of truth.

Analysis now validates every Dataset/ModelView/Evaluation using canonical readers. Dataset
counts are separate from repeated model/baseline evaluation rows. Per-evaluation ablation
rows bind exact Dataset, TrainingInput, model, head, Qwen, serializer and config. DuckDB
computes counts, grouped metrics, token proxies, performance and failure-stage aggregation.
Default discovery omits sealed-test evaluation metrics from tuning projections. Missing
measurements are explicit. The API has one typed order: analyze(registry, store) and
project(registry, store).
