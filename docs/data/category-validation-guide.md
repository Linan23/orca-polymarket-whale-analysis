# Category Validation Guide

Status: protocol defined; human validation not started; category-level modelling remains blocked.

This protocol evaluates the deterministic category reconstruction used for politics, crypto, finance, technology, and geopolitics. It measures label quality and abstention behavior. It does not validate a predictive model, demonstrate whale influence, or support a causal claim.

## Decisions and roles

Two reviewers independently label every sampled event. A third person adjudicates disagreements and quality-control cases. A reviewer must not see the classifier's category, status, scores, matched terms, or the other reviewer's answer before submitting a label. The adjudicator must not have authored the category rules.

Before sampling begins, the manager records reviewer and adjudicator names, the frozen guide revision, source snapshot fingerprint, category configuration hash, classifier code hash, sampling configuration hash, random seed, and generation command. Changing a definition or threshold after labels are visible creates a new protocol version and requires a new primary validation run.

## Allowed human labels

Each event receives exactly one of these labels:

- `politics`
- `crypto`
- `finance`
- `technology`
- `geopolitics`
- `out_of_scope`
- `insufficient_evidence`

Reviewers also provide a short rationale and may select a structured uncertainty reason. `insufficient_evidence` is not a miscellaneous category: use it only when the supplied public event evidence is incomplete, genuinely supports multiple primary categories equally, or does not permit a defensible single label. Do not infer missing context from memory or external research.

## Label definitions

### Politics and geopolitics

Use `politics` for domestic elections, officeholders, legislatures, courts, public policy, referendums, approval, party control, and internal government formation. A domestic election remains politics merely because another country may care about its result.

Use `geopolitics` when the resolution is primarily about relations between states or comparable international actors: cross-border armed conflict, invasion, ceasefire, diplomacy, alliances, sanctions, territorial disputes, nuclear agreements, security guarantees, or international organizations acting in that capacity.

For mixed cases, label the event by the subject whose outcome directly resolves the market. An election determining office is politics; a treaty or ceasefire negotiated after that election is geopolitics. If the supplied evidence makes neither primary subject defensible, use `insufficient_evidence`.

### Crypto, finance, and technology

Use `crypto` when the resolved subject is a cryptoasset, blockchain network or protocol, stablecoin, decentralized-finance system, token, crypto exchange, or a financial product whose defining underlying asset is crypto. A Bitcoin ETF is crypto under this topical taxonomy even though an ETF is a financial instrument.

Use `finance` for interest rates, inflation, employment and macroeconomic releases, equities, bonds, commodities, bank activity, corporate earnings, mergers, acquisitions, initial public offerings, and company valuation. A technology company's earnings or share price is finance because the resolved subject is financial performance.

Use `technology` for product or software releases, technical capabilities, artificial intelligence systems, semiconductors as technology products, hardware, and research or engineering milestones. A model release is technology; the developer's quarterly earnings are finance.

When a market mentions multiple domains, use the object that directly determines resolution rather than a company name or contextual cause. If two objects independently determine resolution and no primary object is stated, use `insufficient_evidence`.

### Out of scope

Use `out_of_scope` for physical sports contests and tournaments, entertainment awards or releases, weather outcomes, and any other event outside the five research categories. Physical sports remains out of scope even when the event mentions betting, revenue, regulation, national teams, or political figures. An event about legislation governing sports is politics only when the law or policy action, rather than a match result, resolves the market.

## Blinded review procedure

1. Generate the sample once from a read-only source snapshot using the frozen sampling configuration and seed.
2. Produce separate reviewer files with different deterministic row orders. Files may contain the run-scoped sample pseudonym, title, description, and source tags needed for labelling. They must not contain raw event, market, contract, condition, transaction, or wallet identifiers; slugs; classifier output; scores; matched terms; or another reviewer's fields.
3. Reviewers work independently and do not discuss sampled records until both files are locked and checksummed.
4. Validate allowed values and completeness, then join reviewer files only by the run-scoped sample pseudonym.
5. Send all disagreements, all cases where either reviewer chose `insufficient_evidence`, and a seeded 10% sample of agreements to adjudication. The adjudicator sees the public event evidence and both labels/rationales, but remains blind to classifier output.
6. Freeze and checksum the adjudicated reference file before computing classifier-quality metrics.

The 10% agreement audit detects systematic shared mistakes without allowing the adjudicator to relabel the entire sample selectively. If the adjudicator changes more than 5% of audited agreements, stop the gate, clarify the guide, and run a newly versioned review rather than silently editing labels.

## Sampling design

Sampling is without replacement at the event level. The generator must record the population size, selected size, and inclusion probability for every stratum. A sample pseudonym must be stable within one run but unlinkable across runs without the local secret salt.

The first wave uses these minimum quotas or a census when the stratum is smaller:

| Stratum | Minimum selected events | Purpose |
| --- | ---: | --- |
| Each automatically classified category | 50 | Estimate category precision and expose minority-category errors |
| `review` | 200 | Measure ambiguity and false abstention across leading-category and exclusion-conflict sub-strata |
| `unmapped` | 100 | Detect missing vocabulary and out-of-scope material |
| `excluded` | 100 | Measure exclusion precision, with physical sports sampled separately |

Within `review`, allocate across the leading category, close in-scope ties, weak-only cases, and in-scope/exclusion conflicts. Within `excluded`, select at least 50 physical-sports cases or a census if fewer exist. Oversample finance, technology, geopolitics, all non-crypto classified categories with fewer than 100 population events, and rare decision paths. Do not replace a rare-stratum census with common crypto events.

These quotas are diagnostic minima, not guarantees of adequate support. After the first wave is frozen, a prespecified second wave may add cases for categories that lack the support defined below. Record each wave and its inclusion probability; never choose additions by looking for cases likely to improve a metric.

## Metrics

Map classifier decisions to six substantive predictions plus abstention:

- `classified` maps to its selected research category.
- `excluded` maps to `out_of_scope`.
- `review` and `unmapped` map to `abstain`.

Exclude adjudicated `insufficient_evidence` records from classifier precision, recall, and accuracy denominators, but report their count, weighted rate, source strata, and uncertainty separately. An abstention on a reference category is a false negative for recall, not a wrong positive for precision.

Report all of the following:

- reviewer count and adjudicator identity;
- raw inter-reviewer agreement and Cohen's kappa over the seven allowed labels;
- per-label agreement and disagreement counts, including `insufficient_evidence`;
- the design-weighted confusion matrix, including the `abstain` prediction column;
- design-weighted precision, recall, and F1 for each of the five categories and `out_of_scope`;
- macro F1 across the five research categories;
- automatic-decision coverage and abstention rate overall and by reference category;
- false in-scope rate for adjudicated `out_of_scope` records and false exclusion rate for in-scope records;
- raw numerator and denominator for every rate, plus population and selected counts for every stratum.

Primary population estimates use inverse-inclusion-probability weights, `population_stratum_size / selected_stratum_size`. Report unweighted diagnostics alongside them, never in place of them. Produce 95% uncertainty intervals with a fixed-seed stratified bootstrap of at least 2,000 replicates, resampling within original strata and preserving their population weights. Report a metric as `not_estimable` rather than substituting zero when its reference or prediction denominator is zero.

## Category-quality gate

The validation run is complete only when every sampled record has two locked reviews and every required adjudication is resolved. Completion does not imply approval.

Reviewer reliability passes when raw agreement is at least 0.90 and Cohen's kappa is at least 0.80. These joint thresholds guard against high apparent agreement caused by an imbalanced label distribution.

Each research category is independently eligible only when it has at least 50 adjudicated reference-positive events and at least 50 classifier-positive events in the reviewed sample, weighted precision is at least 0.85, weighted recall is at least 0.75, and the corresponding 95% lower confidence bounds are at least 0.70 and 0.60. `out_of_scope` additionally requires both weighted precision and recall of at least 0.90 because sports leakage would materially distort the research population.

The overall gate additionally requires macro F1 of at least 0.80 and a weighted false in-scope rate no greater than 0.05 among adjudicated out-of-scope events. Thresholds emphasize precision because unreviewed false positives contaminate category comparisons, while the recall floor prevents a seemingly precise rule from representing only a narrow vocabulary.

A category with fewer than either support minimum is `insufficient_support`, never a pass. A category with zero reference positives has undefined recall; one with zero classifier positives has undefined precision. Either condition blocks that category. Do not average unsupported categories out of the macro result.

Category-level modelling remains blocked unless all five research categories and the overall gate pass. If a category cannot obtain support from a census of the frozen source snapshot, the manager may propose a narrower research scope only through a new issue, updated data contract, renewed review, and explicit disclosure; the category may not be silently dropped. Failed or inconclusive results remain in the evidence ledger.

## Privacy, storage, and evidence

Review files contain public source text but are sensitive local working data. Store them only under an ignored runtime directory with owner-only permissions. Do not commit them, attach them to a GitHub issue or pull request, paste rows into logs, or expose them through the dashboard. Never include wallet data or attempt to link a wallet to a real person.

The local pseudonym salt stays outside Git and outside generated metadata. Logs may contain aggregate counts, hashes, configuration, and validation errors, but never source text or row-level pseudonyms. Delete superseded plaintext review exports when the manager confirms their checksums and replacement artifacts; retain only according to the project's local data-handling decision.

Versioned Git evidence may include the protocol, sampling configuration, schemas, source/config/code hashes, generation commands, aggregate metrics, uncertainty, and reviewer decision. It must not include review rows. No metric may be copied manually into a report or dashboard: generate aggregate evidence from the frozen adjudicated artifact and record its checksum, experiment or validation-run ID, code commit, and independent reviewer decision.

## Required handoff

The validation handoff records the issue, accountable owner, reviewer and adjudicator identities, code commit, frozen guide and configuration hashes, source snapshot fingerprint, generation and scoring commands, sample and adjudicated-artifact checksums, stratum counts and inclusion probabilities, test results, aggregate metrics with uncertainty, limitations, and an independent reviewer decision of `approved`, `approved with limitations`, or `rejected`.

Until that handoff exists and the gate passes, the manifest status remains blocking and category-level claims are prohibited.
