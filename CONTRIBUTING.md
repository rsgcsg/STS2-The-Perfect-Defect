# Contributing

STPD is pre-alpha and evidence-first. Small, reversible changes with clear ownership are
preferred over framework-wide rewrites.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python3 -m unittest discover -s tests -v
python3 -m compileall -q stpd tests
```

The pure test suite must not require STS2, Headless, Connector binaries, Qwen weights, a
GPU, or network access.

## Change categories

- **contract**: schemas, typed ports, serialization, leakage boundaries;
- **environment**: consumption of the public Player Environment only;
- **data**: ingestion, manifests, eligibility, splits, deduplication;
- **representation**: ResearchState/ModelState/ModelAction and Qwen backend;
- **model**: Scheme 1, S2-Simple, S2-SDT;
- **training**: losses, sampling, optimization, checkpoints;
- **evaluation**: B0-B7 benchmarks and statistics;
- **qualification**: current linear-Q and Host/Reference smokes;
- **docs/ops**: project system, evidence, release, and memory.

A change should normally have one primary category.

## Pull request checklist

- [ ] Owning layer and non-goals are stated.
- [ ] Public interfaces are typed and documented.
- [ ] Tests cover success and failure behavior.
- [ ] No Host-local IDs or hidden facts enter model inputs.
- [ ] Data/model/Host revisions and seeds are explicit.
- [ ] New canonical docs are linked from `docs/DOCUMENT_MAP.md`.
- [ ] `docs/STATUS.md` and memory files are updated when facts change.
- [ ] Raw data, weights, credentials, proprietary files, and private paths are absent.
- [ ] Claims distinguish implementation, test, runtime evidence, and inference.

## Evidence

Local outputs belong in ignored directories. Commit only reviewed summaries, manifests,
checksums, and reproducible commands. A result from one source/data/model/Host tuple does
not qualify another tuple.

See [Project System](docs/PROJECT_SYSTEM.md) and [Code Style](docs/CODE_STYLE.md).
