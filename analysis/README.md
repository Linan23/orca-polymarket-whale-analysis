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

## Historical Coverage Profile

Generate aggregate-only source evidence from an existing PostgreSQL analytics database:

```bash
.venv/bin/python analysis/profile_historical_data.py \
  --database-url "$DATABASE_URL" \
  --output-json data_platform/runtime/analysis/historical-profile.json \
  --output-markdown data_platform/runtime/analysis/historical-profile.md
```

The profiler starts a repeatable-read, read-only transaction, verifies the required analytics tables, and reports only aggregate counts, date ranges, category coverage, resolution coverage, and prediction-validation coverage. It also records resolver methods and confidence statistics and warns that heuristic price-threshold or fallback resolution labels are not authoritative outcome ground truth. It never emits database URLs, wallet identifiers, or raw transactions. Runtime outputs remain ignored and must not be treated as model-performance evidence.

## Category Reconstruction Profile

After updating the deterministic research-category rules, measure their aggregate coverage against an existing analytics database:

```bash
.venv/bin/python analysis/profile_category_reconstruction.py \
  --database-url "$DATABASE_URL" \
  --output-json data_platform/runtime/analysis/category-reconstruction-profile.json \
  --output-markdown data_platform/runtime/analysis/category-reconstruction-profile.md
```

This command reads raw category evidence, tags, titles, and descriptions inside a repeatable-read, read-only transaction, but emits only aggregate category, status, confidence, and evidence-source counts. It never writes event identifiers or source text. `review` and `unmapped` results remain excluded from category-level modelling until independently reviewed.
