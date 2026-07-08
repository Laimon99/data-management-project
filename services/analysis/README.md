# analysis — Stage 6: Analysis / research questions

The analysis stage that backs the eleven cross-platform research questions (Q1–Q11). It
does **not** re-derive data: it reads the flat analytics tables materialised in ClickHouse
by the ClickHouse load layer (`services/load/clickhouse`, `uv run dataman-load-clickhouse`)
and turns them into the tables and charts used by the notebooks and the final report.

Import path: `analysis` (PEP 420 namespace package under `services/`).

## What's here

| Module | Role |
|---|---|
| `queries/` | Externalized SQL, one or more `qN_*.sql` per research question (`q0`–`q11`). Loaded via `analysis.queries`. See `queries/README.md`. |
| `notebook.py` | The shared notebook preamble — every `notebooks/qNN_*.ipynb` starts with `from analysis.notebook import *`. Opens a read-only ClickHouse `client`, exposes `run(sql)` and `publish(df, name, caption)`, the house palette, and brand-logo helpers, and configures the static PNG renderer. |
| `export.py` | `to_csv` / `to_latex` writers that publish result tables under the report tables directory (booktabs `\tiny` LaTeX matching the pre-integration report style). |
| `geo.py` | Geographic helpers used by Q7/location analysis — `distance_to_duomo_km`, `classify_center_periphery`, `assign_neighbourhood`. |
| `constants.py` | Shared thresholds (e.g. `CENTER_RADIUS_KM`, `REVIEW_VOLUME_TIERS`, `SPARSE_REVIEW_THRESHOLD`). |
| `config.py` | `AnalysisSettings` + `clickhouse_client` (read-only connection). |
| `dump.py` | Backs the `dataman-analysis-export` CLI (see below). |

## Running the research questions

The questions are executed from the notebooks, which query ClickHouse and publish their
per-question CSV/LaTeX tables (via `publish`) plus chart PNGs into `report/`
(`report/for_visualizations/tables/`, `report/overleaf/images/research_questions/`). Start
ClickHouse first:

```bash
docker compose --profile analytics up -d clickhouse
uv run dataman-load-clickhouse all       # (once) materialise the analytics tables
# then run notebooks/q00_overview … q11_photos
```

## `dataman-analysis-export` — whole-table dump

A separate convenience CLI (`analysis.dump:app`) that dumps whole ClickHouse tables to
CSV/Parquet — useful for offline exploration. Every question reads from the single flat
`restaurants_integrated` table; the three `restaurants_clean_*` tables round out the
pre-integration picture.

```bash
uv run dataman-analysis-export                       # → data/analysis_export/restaurants_integrated.csv
uv run dataman-analysis-export all --format parquet  # every table, parquet
uv run dataman-analysis-export all --out data/analysis_export
```

It is read-only (`SELECT * FROM <table>`); Parquet needs `pyarrow`, CSV is the default.
