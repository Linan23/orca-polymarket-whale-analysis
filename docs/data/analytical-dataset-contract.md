# Analytical Dataset Contract

This contract defines the row semantics required before modelling. It complements [`configs/data-manifest.yaml`](../../configs/data-manifest.yaml), [`configs/splits.yaml`](../../configs/splits.yaml), [`configs/experiments.yaml`](../../configs/experiments.yaml), and [`configs/whale-score.yaml`](../../configs/whale-score.yaml).

## Unit of observation

One row represents one modeled contract side at one `feature_cutoff_at`. Every feature must be computable using records whose effective timestamps are at or before that cutoff. Multiple cutoffs for one condition are allowed, but all rows for the condition remain in one dataset partition.

Required identity and audit fields are:

| Field | Purpose |
| --- | --- |
| `dataset_version` | Immutable analytical dataset version |
| `row_id` | Stable opaque row identifier, not a wallet address |
| `condition_ref` | Market-group key used only for grouping and auditing |
| `market_contract_ref` | Contract-side audit identifier, excluded as a learned feature |
| `feature_cutoff_at` | Latest timestamp information may influence features |
| `market_end_time` | Time-to-close calculation and audit field |
| `category` | Reviewed normalized category |
| `source_data_cutoff_at` | Maximum source timestamp actually consumed |

For every row, `source_data_cutoff_at <= feature_cutoff_at` must hold.

## Targets

Let `p(t)` be the modeled contract-side probability at cutoff `t`, bounded to `[0, 1]`.

- `probability_change_12h = p(t + 12h) - p(t)` is the secondary regression target.
- `probability_change_24h = p(t + 24h) - p(t)` is the primary regression target.
- Both movement targets must lie in `[-1, 1]`.
- `resolved_binary_outcome` is an auxiliary target in `{0, 1}` for the same modeled side.

## Frozen target-alignment rule

Eligible probability sources, in priority order, are an exact-contract transaction price and an exact-contract orderbook midpoint with valid bid and ask. Mutable current-state `last_trade_price`, final resolution price, and an opposite-contract price without an explicit side conversion are prohibited.

The feature price uses a backward/as-of rule: select the latest eligible observation at or before `feature_cutoff_at`. A future target uses a forward-only rule: select the earliest eligible observation at or after the exact 12-hour or 24-hour timestamp. An observation before the horizon is never a valid target. The maximum forward delay is 60 minutes for both horizons.

Duplicate candidates are reduced to one deterministic observation per contract, cutoff, and horizon. For the feature price, ties resolve by source priority, latest effective timestamp, and stable source record ID. For future targets, ties resolve by earliest effective timestamp, source priority, and stable source record ID.

If no valid future observation exists within the tolerance, exclude the row from that horizon only. Count exclusions by horizon, reviewed category, attempted source, and reason. Do not fill a missing horizon using final resolution or a later convenient price. This alignment rule is frozen for dataset version one; any change requires a new dataset version and renewed comparison of every model.

Targets are permitted to use future information only to construct labels after features are frozen. Target fields must never enter feature preprocessing, selection, reliability scoring, or tuning inputs.

## Final-outcome label quality

The historical source currently contains 1,840 winning-outcome labels, but 1,821 come from `trade_price_extreme_fallback` at confidence 0.60 and 19 from `last_trade_price_threshold` at confidence 0.75. Neither resolver is an authoritative resolution source. Only 27 contracts are marked closed in the inspected snapshot, leaving 1,813 resolution rows associated with contracts not marked closed there.

Primary final-outcome evaluation requires an authoritative resolution source with persisted provenance. Existing heuristic labels are allowed only for sensitivity analysis, must retain resolver method and confidence, and must be evaluated separately from the authoritative sample. Conclusions that disappear when heuristic labels are removed cannot be headline claims.

## Feature families

### Price state

Current probability, distance from 0.5, recent price changes, spread, and time-to-close, all observed at or before the cutoff.

### Prior market activity

Trailing-window trade counts, volume, buy/sell imbalance, distinct trader counts, and liquidity/orderbook summaries. Windows end at the cutoff and do not use future rows.

### Prior whale activity

Trailing-window whale trade counts, signed notional pressure, participation, concentration, and recency. Whale designation must be point-in-time.

### Prior trader reliability

Volume, profitability, consistency, and history components calculated only from transactions and resolutions available before the cutoff. The current market outcome and post-cutoff profitability are excluded. Traders below the history threshold receive the conservative population prior defined in `configs/whale-score.yaml`.

### Controls

Reviewed category and time controls that are available when the prediction is made. Raw text, wallet identifiers, condition identifiers, and contract identifiers are not learned features.

## Leakage prohibitions

- No transaction, orderbook, position, resolution, or score record effective after `feature_cutoff_at` may influence a feature.
- Reliability for a trader cannot use the current market's eventual outcome.
- Normalization, imputation, category encodings, feature selection, and learned score transformations are fit on training data only.
- A condition and all of its snapshots belong to exactly one partition.
- Tuning and feature decisions cannot inspect the locked final test period.
- Cached tables are acceptable only when their source-data cutoff is persisted and verified for each row.

## Split contract

Use the grouped chronological strategy in `configs/splits.yaml`: 60% train, 20% validation, and 20% locked test, grouped by `condition_ref`. Partition boundaries must satisfy strict time order: the maximum feature cutoff in an earlier partition is earlier than the minimum cutoff in the next partition. Boundary markets that would violate both grouping and time order must be moved wholly to one side or excluded with an audit count.

Rolling evaluation uses at least five expanding-window folds while preserving market grouping and time order. The final test partition is evaluated once after model, feature, and threshold decisions are frozen.

## Exclusions and reporting

Exclude rows with an unreviewed category, invalid probability, missing cutoff, unresolved auxiliary label when that task is evaluated, unavailable horizon target, or irreconcilable point-in-time provenance. Report exclusions by reason and category rather than silently dropping them.

The frozen dataset profile must include row and market counts, target availability, missingness, category balance, cutoff ranges, horizon-alignment losses, target-source usage, resolution provenance and confidence, trader-history coverage, and checksums. No training begins until the data, resolution-label quality, target-alignment, and leakage checks independently pass.
