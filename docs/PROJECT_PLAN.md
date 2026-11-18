# Project Plan

## Outcome

By December 5, 2026, the repository must provide a reproducible analysis of whether reliable-whale activity predicts Polymarket probability movement 12 and 24 hours later, together with a working local dashboard demonstration.

The primary outcome is rolling out-of-sample probability-change error. Final market outcome is an auxiliary classification task. Trader profitability and reliability support the whale score and influential-trader analysis rather than becoming unrelated projects.

## Research Scope

- Categories: politics, crypto, finance, technology, and geopolitics.
- Primary horizons: 12 hours and 24 hours.
- Whale reliability inputs: volume, profitability, consistency, and prior history.
- Models: price/no-change benchmark, regularized linear baseline, Random Forest, and LightGBM.
- Interpretation: predictive association only; causal claims are out of scope.
- Audience: researchers, risk analysts, and casual users.
- Demonstration: local React/FastAPI application.

## Milestones

### November 18-20: repository and contracts

- Preserve and tag the working baseline.
- Establish agent roles, issue templates, pull-request checks, and CI.
- Freeze configuration schemas for categories, splits, whale scoring, and experiments.
- Record repository, data, model, analysis, claim, dashboard, and release gates.

### November 20-23: data

- Recover approved historical records and collect newer public Polymarket data where feasible.
- Normalize the five research categories.
- Produce a versioned data manifest with sources, dates, row counts, licence notes, and checksums.
- Verify point-in-time feature construction and chronological grouped splits.
- Generate the first reproducible EDA report.

### November 23-27: models

- Implement common evaluation for all benchmarks and models.
- Train the no-change benchmark, regularized linear baseline, Random Forest, and LightGBM.
- Evaluate 12-hour and 24-hour movement under identical rolling folds.
- Build the reliability score and influential-trader analysis.

### November 27-30: optimisation and robustness

- Run a declared hyperparameter search without accessing the final test period.
- Run reliability-component and feature-family ablations.
- Report fold-level variability and paired confidence intervals.
- Test time shift, category, liquidity, cold-start, and probability-range subsets.
- Freeze new feature work after November 30.

### November 30-December 2: reports and dashboard

- Generate all report tables and figures from approved artifacts.
- Connect the dashboard only to stable, reviewed result schemas.
- Display sample sizes, uncertainty, and analytical-signal disclaimers.

### December 2-4: independent verification

- Reproduce headline results from a clean checkout.
- Audit each user-facing claim against the evidence registry.
- Run full API, database, analysis, and frontend checks.
- Rehearse the local demonstration with equal speaking time for all three members.

### December 5: release

- Run the release verification command.
- Confirm a clean working tree and passing CI.
- Tag the final commit and preserve the experiment and result manifests.

## Acceptance Gates

1. **Repository gate:** clean setup, secret scan, migrations, lint, tests, and build.
2. **Data gate:** provenance, licence, date coverage, category coverage, checksum, missingness, and leakage tests.
3. **Model gate:** shared chronological grouped splits, required baselines, deterministic configurations, and untouched final test period.
4. **Analysis gate:** learning curves, error analysis, at least five folds or seeds, ablations, uncertainty, and stress tests.
5. **Claim gate:** every headline statement maps to reproducible evidence and an independent reviewer decision.
6. **Dashboard gate:** the UI consumes approved artifacts and does not independently recalculate headline metrics.
7. **Release gate:** fresh-clone reproduction, full verification, demonstration rehearsal, and tagged release.

Negative or inconclusive results are valid outcomes and must remain visible. No metric may be copied manually into a report or dashboard when it can be generated from a registered experiment artifact.
