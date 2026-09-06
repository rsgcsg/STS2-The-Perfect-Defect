# New Engineer Guide

STPD studies candidate-ranking models using exact Platform evidence. It does not run a
second game engine. Start with README, AGENTS, [Document Map](DOCUMENT_MAP.md),
[Current Context](memory/CURRENT.md) and the owning source/tests.

```bash
uv sync --locked --all-extras
npm ci
uv run --locked python tools/project.py context
uv run --locked python tools/project.py check
```

Resolve the current remote develop and active PRs before work. Historical combat-v0 and H1
smokes remain valuable but are not the next Full-Run research campaign. Learn the authority
boundary before changing data: H != S, public actions != authoritative semantic actions.

[Engineering Governance](ENGINEERING_GOVERNANCE.md) explains evidence and review;
[Testing](TESTING.md) defines the portable gate; [Development Workflow](DEVELOPMENT_WORKFLOW.md)
defines collaboration. Neither a synthetic smoke nor a finished training process is a
scientific result. Source/test evidence, Human runtime evidence and model-quality evidence
must be reported separately.
