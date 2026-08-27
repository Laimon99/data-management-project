# Contributing

Contributions are welcome when they preserve reproducibility, provenance, and the
stage-based architecture.

## Local setup

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Tests must not make real network calls or require running MongoDB/ClickHouse unless they
are explicitly marked as external integration tests.

## Pull requests

- Create a focused branch from the latest `main`.
- Keep each pull request small enough to review as one coherent change.
- Explain the motivation, affected pipeline stage, validation performed, and any data
  or schema migration.
- Add or update tests for behavior changes.
- Update the closest service README and the central docs when interfaces or output
  paths change.
- Do not combine generated output refreshes with unrelated source changes.
- Request review from the other project authors before merging.

Use clear commit subjects such as `feat:`, `fix:`, `docs:`, `test:`, `ci:`, and
`chore:`. Merge only after GitHub Actions passes.

## Data and generated files

Do not commit complete raw datasets, database exports, browser profiles, credentials,
or local `.env` files. Public data changes should be limited to minimized samples,
schemas, aggregate metrics, and results that comply with [`DATA_USAGE.md`](DATA_USAGE.md).

Generated artifacts belong under `artifacts/`; review-ready PDFs belong under
`deliverables/`; editable report and diagram sources belong under `report/` and
`diagrams/`.

## Service boundaries

Keep code within its pipeline stage under `services/extract`, `services/load`, or
`services/transform`, or in the dedicated assessment/analysis packages. Avoid new
monolithic scripts and preserve source provenance throughout transformations.
