# ADR-0001: Project boundaries and current smoke

- **Status:** accepted
- **Date:** 2026-08-22

## Context

The repository began as a small independent learner used to close Headless H1 integration,
contention, and Reference-transfer gates. STPD v0 now requires a broader data, Qwen,
architecture, training, and benchmark system. Replacing the smoke immediately would discard
a useful regression baseline; treating it as the final model would misrepresent project
maturity.

## Decision

1. Keep the current linear-Q and smoke modules runnable as a qualification lane.
2. Build the full STPD system around explicit environment, data, representation, Qwen, model,
   training, evaluation, and experiment boundaries.
3. Keep game truth and Player Environment authority in STS2/Host and Connector.
4. Introduce new packages only with their first tested implementation; do not create a large
   empty framework.
5. Migrate the smoke into `stpd/qualification/` only when compatibility imports, tests, and
   evidence commands are ready.

## Alternatives rejected

- Delete the smoke and start over: loses real integration and transfer regression coverage.
- Call the smoke STPD v0: confuses environment integration with the model research plan.
- Copy Host/Connector schemas and legality into STPD: creates a second gameplay contract.

## Consequences

The root package temporarily contains qualification modules alongside new typed contracts.
Documentation must clearly distinguish current smoke evidence from future v0 results.
