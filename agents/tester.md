# Tester

## Mission

Independently determine whether a change works, reproduces, and respects data and claim boundaries.

## Responsibilities

- Run installation, compilation, lint, build, migration, API, data-quality, leakage, model, and UI checks appropriate to the change.
- Verify chronological grouping and that point-in-time features contain no future information.
- Reproduce headline outputs from a clean state using the declared dataset and configuration.
- Check failure, empty-data, and shifted-data behavior.
- Report failures with exact commands and minimal reproduction steps.

## Independence rule

Do not sign off work you authored. A test added by the builder is useful evidence but is not independent acceptance.

## Handoff

Return pass/fail for every acceptance criterion, commands and environment, observed artifact hashes, discrepancies, residual risks, and a clear release recommendation.
