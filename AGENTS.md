# Agent Operating Contract

This repository is a reproducible research and local demonstration project about whether historically reliable Polymarket whale activity predicts 12-hour and 24-hour probability movement. Treat predictive association as the claim boundary; do not use causal language unless a causal design has been reviewed and approved.

## Project identity

- Authors: Anthony, Noah, and Uday. These names do not imply fixed role assignments.
- Delivery deadline: December 5, 2026.
- Delivery format: a GitHub repository, generated reports, and a local dashboard demonstration. A notebook is not required.
- Primary categories: politics, crypto, finance, technology, and geopolitics.
- Primary models: a no-change benchmark, a simple linear baseline, Random Forest, and LightGBM.

## Roles

Every task has one accountable role. A person or agent may cover several roles, but a builder must not provide the final verification of its own substantive change.

| Role | Accountable for | Role card |
| --- | --- | --- |
| Manager | Scope, task graph, acceptance criteria, merge order, release decision | [agents/manager.md](agents/manager.md) |
| Data builder | Ingestion, provenance, category normalization, point-in-time datasets | [agents/data-builder.md](agents/data-builder.md) |
| ML builder | Baselines, Random Forest, LightGBM, tuning, evaluation code | [agents/ml-builder.md](agents/ml-builder.md) |
| Analyst | EDA, hypotheses, reliability/influence definitions, statistics, interpretation | [agents/analyst.md](agents/analyst.md) |
| Dashboard builder | Local UI and API integration of approved results | [agents/dashboard-builder.md](agents/dashboard-builder.md) |
| Tester | Independent functional, data, leakage, and reproducibility verification | [agents/tester.md](agents/tester.md) |
| Reviewer | Claim-to-evidence audit, methodological review, rubric/release review | [agents/reviewer.md](agents/reviewer.md) |

## Mandatory workflow

1. The manager defines a bounded issue before implementation begins.
2. The issue names its owner, allowed paths, dependencies, inputs, outputs, acceptance commands, and required evidence.
3. Work happens on a focused branch or isolated worktree. Do not edit a path currently owned by another active task.
4. The builder produces the handoff package defined below.
5. A tester who did not author the change runs the acceptance commands.
6. A reviewer independently checks analytical claims and evidence when results or user-facing copy change.
7. The manager merges only after required gates pass.

Preferred branch prefixes are `data/`, `model/`, `analysis/`, `ui/`, `test/`, `docs/`, and `chore/`. Keep one concern per pull request and merge in dependency order: data contract, features, models, analysis, API, dashboard, release.

## Path ownership

Ownership is a coordination default, not permission to ignore task-specific instructions.

| Paths | Primary role | Required consultation |
| --- | --- | --- |
| `data_platform/ingest/`, `data_platform/db/`, migrations, dataset builders | Data builder | Tester for schema/data changes; ML builder for feature contracts |
| `data_platform/ml/`, model training/evaluation jobs | ML builder | Analyst for metrics; tester for leakage/reproducibility |
| `analysis/`, analytical report generators, experiment interpretations | Analyst | ML builder for model semantics; reviewer for claims |
| `my-app/`, dashboard-facing read endpoints | Dashboard builder | Reviewer for copy/claims; tester for UI/API behavior |
| `tests/`, validation scripts, CI acceptance gates | Tester | Affected builder for expected behavior, never for final sign-off |
| `reports/`, model card, data documentation, evidence ledger | Analyst or reviewer | Tester must reproduce headline evidence |
| `AGENTS.md`, `agents/`, task graph, release checklist | Manager | Reviewer for governance or release changes |

If a task crosses ownership boundaries, the manager must split it or explicitly record shared ownership and merge order before edits begin.

## Evidence rules

- Never type a final metric manually into a report or dashboard. Generate it from a versioned artifact.
- Each headline claim must identify a dataset version/hash, experiment ID, code commit, metric with uncertainty, artifact path, and reviewer decision.
- Keep the final test period unavailable to tuning and feature selection.
- Reliability and influence features must use only information available before the prediction timestamp.
- Report negative and inconclusive findings. Do not hide failed categories or stress tests.
- Include sample size and uncertainty with rankings and performance claims.
- Raw/private data, credentials, large snapshots, and generated models stay outside Git. Commit manifests, schemas, hashes, and reproduction commands instead.
- Dashboard copy may display only approved result fields. Exploratory results must be visibly labeled and excluded from headline conclusions.

## Handoff package

Every completed task must report:

```text
Issue/task:
Role and owner:
Commit SHA:
Changed files:
Inputs and dataset/artifact hashes:
Commands executed:
Test results:
Generated artifacts and checksums:
Claims or metrics changed:
Assumptions and limitations:
Known risks:
Recommended next step:
```

Downstream work consumes committed files or documented schemas, not another agent's uncommitted workspace.

## Acceptance gates

- Repository: secret scan, deterministic install, Python compilation, frontend lint/build, migrations, and CI.
- Data: provenance, licence, time coverage, row counts, category coverage, missingness, checksum, and point-in-time leakage tests.
- Models: common chronological grouped split, required baselines, Random Forest, LightGBM, deterministic configurations, and an untouched final test period.
- Analysis: at least five folds or seeds, uncertainty intervals, learning curves, ablations, subgroup/stress evaluation, and practical-effect interpretation.
- Claims: every user-facing conclusion maps to approved reproducible evidence and avoids unsupported causal language.
- Dashboard: approved schemas only, sample size and uncertainty shown, local smoke tests passed.
- Release: fresh-clone reproduction, full CI, independent claim audit, local demo rehearsal, clean Git state, and a tagged release.

After November 30, 2026, the manager should accept only fixes, evidence completion, verification, and presentation work unless a blocking defect requires a scoped exception.
