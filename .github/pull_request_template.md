## Purpose

Describe the bounded issue this pull request resolves and link it with `Closes #...`.

## Ownership and scope

- Agent role:
- Paths authorized by the issue:
- Paths changed outside that scope (explain or write `none`):

## Evidence

- Dataset version/hash (`not applicable` if no data was used):
- Experiment or claim IDs (`not applicable` if none changed):
- Generated artifact paths/checksums:
- Headline metrics changed: yes/no

## Verification

List exact commands and results. At minimum, run the relevant subset of:

```text
scripts/verify_repository.sh
scripts/reproduce_analysis.sh --structural-only
```

## Analytical safety

- [ ] Features and scores use only information available at prediction time.
- [ ] The final test period was not used for tuning.
- [ ] Predictive association is not described as causation.
- [ ] Negative or inconclusive results remain visible.
- [ ] Dashboard/report claims point to approved generated evidence.
- [ ] No raw datasets, credentials, or private artifacts were committed.

## Handoff

- Commit SHA:
- Assumptions and limitations:
- Remaining risks or follow-up issues:
- Independent tester/reviewer:
