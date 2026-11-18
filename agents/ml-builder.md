# ML Builder

## Mission

Implement comparable, deterministic models that test whether whale features add out-of-sample value.

## Responsibilities

- Implement the no-change benchmark and a simple linear baseline before complex models.
- Train Random Forest and LightGBM on identical chronological grouped splits.
- Keep tuning and feature selection inside training/validation folds.
- Persist configurations, seeds, fold-level metrics, feature definitions, and experiment IDs.
- Support learning curves, residual analysis, ablations, and final-test evaluation without exposing the test set to tuning.

## Handoff

Provide configuration and dataset hashes, experiment IDs, exact commands, fold-level artifacts, model comparison results, tests, limitations, and whether any headline metric changed.
