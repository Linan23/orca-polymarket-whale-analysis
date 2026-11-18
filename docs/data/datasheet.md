# Historical Data Datasheet

Status: source profiled; analytical dataset not frozen.

The canonical machine-readable record is [`configs/data-manifest.yaml`](../../configs/data-manifest.yaml). Aggregate counts below describe an older Orca PostgreSQL snapshot inspected with read-only queries on November 18, 2026. They describe potential source material, not a released training dataset or validated research sample.

## Intended use

The approved dataset will test whether information available from historically reliable Polymarket whales adds out-of-sample predictive information about market-probability movement 12 and 24 hours later. Final market outcome is an auxiliary task. The data must not be used to identify wallet owners, claim causal influence, or provide trading advice.

## Source and collection

The source records originate from public Polymarket API observations collected by the repository's trade-ingest, orderbook-snapshot, market-trader-crawl, and resolved-condition jobs. The inspected snapshot is stored in an external local Docker volume from a prior Orca deployment and is intentionally not committed to Git.

Collection provenance is only partially documented. Before the data gate can pass, the team must verify collection logs or rebuild the source snapshot, record the exact API endpoints and parameters, and freeze an immutable snapshot checksum.

No dataset licence is asserted by this repository. The applicable Polymarket terms and any redistribution restrictions must be reviewed and recorded before publishing a row-level derived dataset. Until then, raw and analytical datasets remain external local artifacts.

## Aggregate historical coverage

| Relation or measure | Count |
| --- | ---: |
| Market events | 4,484 |
| Market contracts | 10,519 |
| Transactions | 1,190,139 |
| Distinct traders represented in transactions | 94,307 |
| Traded contracts | 10,483 |
| Position snapshots | 96 |
| Orderbook snapshots | 21,394 |
| User-account records | 129,334 |
| Whale-score snapshots | 11,923,605 |
| Resolved conditions | 1,840 |
| Contracts marked closed | 27 |
| Stored prediction snapshots | 964 |
| Stored prediction validations | 2 |

Transaction timestamps run from October 14, 2025 at 06:14:55 UTC through April 27, 2026 at 20:58:52 UTC. Resolved-condition timestamps run from March 31, 2025 through June 30, 2026. These ranges require consistency checks because resolution records extend beyond the transaction collection window.

## Resolution-label quality

All 1,840 resolved-condition rows contain a winning-outcome label, but none is currently verified as authoritative. Of those labels, 1,821 were produced by `trade_price_extreme_fallback` at confidence 0.60 and 19 by `last_trade_price_threshold` at confidence 0.75. Both methods infer resolution from trade prices and are heuristic fallbacks.

The source snapshot contains only 27 contracts marked closed. Every one has a resolution row, while 1,813 resolution rows refer to contracts not marked closed in the same snapshot. This discrepancy may reflect stale contract status, collection timing, or over-inclusive fallback resolution. It prevents the existing labels from serving as the primary final-outcome ground truth without review.

Primary final-outcome evaluation must use resolutions verified against an authoritative source with persisted provenance. Heuristic labels may be used only in a clearly labeled sensitivity analysis that compares results with and without them. The data gate remains blocked until resolver methods, confidence, provenance, and the closed-contract discrepancy have been reviewed.

## Category quality

Raw category metadata is not ready for analysis. Of 4,484 events, 4,474 are uncategorized. The remaining raw labels are sparse and inconsistent: `World` (3), `Starmer` (2), and one each for `exchange`, `Finance`, `France`, `India`, and `Russia`.

A deterministic profiler now measures reconstruction coverage from retained tags, event text, and source labels without emitting event text, identifiers, tags, slugs, or wallet data. Its runtime output is descriptive evidence only and is not a reviewed label set or model-performance result. A privacy-preserving validation review must assess ambiguity, unassigned coverage, and category balance before category-level modelling.

The frozen review definitions, blinded two-reviewer procedure, stratified sampling requirements, metrics, and approval thresholds are specified in the [category validation guide](category-validation-guide.md).

Category-specific results are prohibited until ambiguous records are reviewed or excluded and the independent category-quality gate passes.

## Frozen price-alignment rule

The version-one target-alignment rule uses exact-contract transaction prices first and exact-contract orderbook midpoints second. It excludes mutable current-state prices and final resolution prices. The feature price is the latest eligible observation at or before `feature_cutoff_at`. A 12-hour or 24-hour target uses the earliest eligible observation at or after the exact horizon, never an observation before it, with a maximum delay of 60 minutes for either horizon.

Timestamp ties are resolved deterministically by timestamp, source priority, and stable source record ID. If no observation exists inside the forward tolerance, the row is excluded only from that horizon. Exclusions must be counted by horizon, category, attempted source, and reason. This rule must remain frozen across model comparisons; changing it requires a new dataset version.

## Privacy and sensitivity

Wallet activity is public, but public availability does not justify identifying the people behind wallets. The project will not link wallet addresses to real-world identities. Raw wallet rows and full database snapshots must remain outside Git. Reports and the local demonstration should use aggregates or stable pseudonyms and disclose sample sizes without unnecessarily exposing wallet addresses.

## Quality and representativeness risks

- Transaction coverage may reflect crawler scope and collection outages rather than the full market.
- Orderbook and position coverage is sparse relative to transactions.
- Profitability labels can be incomplete until markets resolve and all relevant activity is observed.
- Existing winning-outcome labels are heuristic price-based inferences, not authoritative resolutions.
- Whale-score snapshots vastly outnumber resolved markets, so repeated correlated rows must not be treated as independent observations.
- The historical period may not represent later market regimes, categories, or participant behavior.
- Only two stored predictions have validation rows; existing prediction records cannot support headline performance claims.
- Survivorship, selection, missingness, thin-market, and temporal-drift risks require explicit measurement.

## Version and checksum policy

The provisional dataset ID is `polymarket_whale_movement_v1`. Its version and SHA-256 remain null until provenance, licence review, category normalization, resolution-label review, target-alignment review, missingness, leakage, and grouped-split checks pass. When frozen, the manifest must record the immutable snapshot version, analytical artifact path, checksum, generation command, schema version, code commit, and aggregate profile.

Large source data, analytical rows, model binaries, and wallet-level artifacts remain ignored. Git stores only manifests, schemas, aggregate evidence, checksums, and reproduction code.
