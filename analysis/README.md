# Executable Analysis

This directory will contain deterministic entry points that generate the project's EDA, model comparisons, ablations, robustness checks, influential-trader rankings, figures, and tables.

## Rules

- Analysis code consumes a versioned dataset manifest and explicit configuration.
- Generated metrics include an experiment ID, dataset fingerprint, code revision, split definition, and random seed.
- All models use the same chronological, market-grouped evaluation folds.
- Preprocessing, trader reliability, and feature selection use training-period information only.
- The final test period is not available to tuning commands.
- Reports and dashboard endpoints consume generated artifacts rather than manually transcribed metrics.
- Analytical conclusions describe association, not causation.

The top-level reproduction command will be `scripts/reproduce_analysis.sh`. Until the data gate is satisfied, that command must fail clearly or run only fixture-backed structural checks; it must never fabricate research results.
