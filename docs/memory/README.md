# Project Memory

This directory is the shared short-term memory for humans and agents.

## Read at task start

1. `CURRENT.md` — current phase, exact working truth, immediate priorities.
2. `DECISIONS.md` — accepted decisions; append-only except typo/link fixes.
3. `OPEN_QUESTIONS.md` — unresolved items and evidence needed.
4. `HANDOFF.md` — latest coherent checkpoint and next action.

## Update at task end

- Rewrite `CURRENT.md` so it stays short and true.
- Append durable accepted decisions to `DECISIONS.md`; add an ADR when architectural.
- Close, split, or add questions in `OPEN_QUESTIONS.md`.
- Rewrite `HANDOFF.md` with exact refs, changes, checks, evidence, risks, and next step.

Memory is not a second architecture or status system. When it conflicts with code, schemas,
`STATUS.md`, or an ADR, resolve the conflict and then repair memory.
