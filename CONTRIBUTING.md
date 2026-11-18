# Contributing

All work is organized through bounded GitHub issues and independently reviewed pull requests. Read [AGENTS.md](AGENTS.md) before starting.

## Start a task

An issue must state:

- accountable role and owner;
- problem and acceptance criteria;
- allowed paths and explicit exclusions;
- dependencies and expected input schemas;
- outputs and evidence to generate;
- exact verification commands;
- whether analytical claims or metrics may change.

Use a focused branch such as `data/123-category-map`, `model/142-rolling-baseline`, `analysis/155-whale-ablation`, `ui/171-evidence-panel`, or `test/180-release-gate`.

## Pull requests

Keep one concern per pull request. Include:

- linked issue;
- changed files and rationale;
- dataset manifest/hash and experiment ID, when applicable;
- commands run and their results;
- generated artifact paths/checksums;
- affected claims and metrics;
- assumptions, limitations, and remaining risks;
- the handoff package from `AGENTS.md`.

Builders cannot approve their own analytical or release-critical work. Changes to reported results require both independent test evidence and reviewer approval.

## Required local checks

Run checks proportionate to the change. The baseline repository checks are:

```bash
.venv/bin/python -m compileall data_platform scripts
.venv/bin/python scripts/secret_scan.py
npm --prefix my-app run lint
npm --prefix my-app run build
docker compose config --quiet
```

Database and API changes also require migrations against an isolated database and `data_platform/tests/smoke_validate.py`. Analytical changes require the relevant data-quality, leakage, reproducibility, and model checks on the declared dataset version.

## Commit and data hygiene

- Use concise imperative commit messages.
- Never commit `.env`, credentials, database exports, raw wallet datasets, runtime artifacts, private keys, or generated model binaries.
- Do not rewrite or delete another contributor's work to simplify a change.
- Do not update a result narrative without regenerating its evidence.
- Do not tune on the final test set.
- Preserve negative and inconclusive results.

The target release date is December 5, 2026. From December 1 onward, favor reproducibility, verification, documentation, and demonstration reliability over new features.
