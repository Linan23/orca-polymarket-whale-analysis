# Tests

`data_platform/tests/` contains backend smoke, data-quality, readiness, and ML guardrail checks.

## Common Checks

```bash
.venv/bin/python data_platform/tests/analytical_data_contract_check.py
.venv/bin/python data_platform/tests/research_category_normalization_check.py
.venv/bin/python data_platform/tests/category_validation_sample_check.py
.venv/bin/python data_platform/tests/smoke_validate.py
.venv/bin/python data_platform/tests/data_quality_check.py
.venv/bin/python data_platform/tests/week45_readiness_check.py
.venv/bin/python data_platform/tests/history_partition_check.py
```

`analytical_data_contract_check.py` is database-independent. It validates the
versioned data manifest, five-category research scope, bounded 12-hour/24-hour
targets, grouped chronological splits, locked final test period, prior-only
whale reliability features, privacy exclusions, and reliability-score weights.
It also inspects `git ls-files` and rejects tracked raw datasets, database dumps,
runtime outputs, archives, and trained-model artifacts. The narrow exceptions
are the approved SQL source file, source/configuration JSON paths, and generated
aggregate CSV/TSV evidence under `reports/tables/`.

`research_category_normalization_check.py` is database-independent. It uses
synthetic fixtures to validate the exact five-category scope, deterministic
classification, politics/geopolitics separation, crypto/finance conflicts,
technology classification, physical-sports exclusion, weak and unmapped review
behavior, configuration validation, retained row-level audit evidence, and the
absence of raw evidence from aggregate profiler output.

`category_validation_sample_check.py` is database-independent. It exercises
the real in-memory sampler with synthetic events and verifies deterministic
stratification, minority and exclusion quotas, run-scoped pseudonyms, two
separately ordered blinded reviewer templates, aggregate reconciliation,
spreadsheet-formula neutralization, local-runtime path confinement, and
fail-closed handling of missing salts or unsafe privacy configuration.

## ML Checks

```bash
.venv/bin/python data_platform/tests/ml_report_endpoint_check.py
.venv/bin/python data_platform/tests/market_scope_finance_check.py
.venv/bin/python data_platform/tests/ml_category_validation_check.py
.venv/bin/python data_platform/tests/ml_market_scope_guardrail_check.py
.venv/bin/python data_platform/tests/ml_trend_magnitude_guardrail_check.py
```

## Model/Feature Checks

```bash
.venv/bin/python data_platform/tests/market_ml_dataset_check.py
.venv/bin/python data_platform/tests/market_ml_baseline_check.py
.venv/bin/python data_platform/tests/market_lightgbm_check.py
.venv/bin/python data_platform/tests/market_feature_set_comparison_check.py
```

## CI Baseline

At minimum, run:

```bash
.venv/bin/python -m compileall data_platform scripts
.venv/bin/python scripts/secret_scan.py
.venv/bin/python data_platform/tests/smoke_validate.py
npm --prefix my-app run lint
npm --prefix my-app run build
```

Some checks require a migrated database and current data. Use `--require-data` only when validating an actual populated environment.
