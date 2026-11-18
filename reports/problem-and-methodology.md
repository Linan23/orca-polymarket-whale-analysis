# Problem and Methodology

Status: planned; no empirical claims have been approved.

## Research question

Does trust-weighted whale activity add out-of-sample predictive information about Polymarket probability movement 12 and 24 hours later beyond current price and ordinary market activity?

## Authors

Anthony, Noah, and Uday.

## Intended audiences

Researchers, casual users, and risk analysts.

## Tasks and targets

- Primary: 24-hour probability-change regression.
- Secondary: 12-hour probability-change regression.
- Auxiliary: final resolved-outcome classification.
- Analytical: influential-trader ranking with sample size, uncertainty, and stability.

## Evaluation protocol

Document the grouped chronological split, point-in-time feature cutoffs, locked final test set, metrics, error costs, and non-ML price-persistence benchmark here. The canonical settings live in `configs/splits.yaml` and `configs/experiments.yaml`.

## Interpretation boundary

The project studies predictive association. It does not claim that whale activity causes price movement and must not be presented as financial advice.
