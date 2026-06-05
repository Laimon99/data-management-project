# quality_assessment

Stage 5 of the Data Management pipeline. This service profiles the raw Google
Places, Tripadvisor, and TheFork datasets and generates reproducible quality
metrics for the final report.

The service does not modify raw datasets. It reads from `data/raw/`, writes
derived quality artifacts under `data/quality/`, and regenerates report-ready
Markdown and LaTeX tables.

## Purpose

The quality assessment supports the project question about consistency and
quality of online restaurant reviews in the Milan area. It is a pre-integration
baseline: it measures whether the three acquired source datasets are complete,
valid, reliable, and ready for later entity matching.

Current assessed dimensions:

- **Completeness**: non-missing values for source-specific relevant fields.
- **Critical completeness**: non-missing values for fields needed by matching or
  analysis, such as identifiers, names, addresses, ratings, review counts, and
  coordinates where available.
- **Validity / consistency**: rating values in the expected platform scale,
  parsable non-negative review counts, and valid coordinate pairs.
- **Uniqueness**: duplicate source identifiers and duplicate normalized
  name/address keys.
- **Timeliness**: availability of scrape or acquisition timestamps.
- **Reliability**: records with few reviews are flagged because ratings based on
  sparse evidence are less reliable.

## Inputs

Default input files:

| Source | File | Format |
|---|---|---|
| Google Places | `data/raw/google_places/restaurants_seed.jsonl` | JSONL |
| Tripadvisor | `data/raw/tripadvisor/tripadvisor_scraper_results.json` | JSON |
| TheFork | `data/raw/thefork/thefork_milan_restaurants_normalized.json` | JSON |

Notes:

- Google Places is the geospatial reference source and currently has complete
  coordinate coverage.
- Tripadvisor currently has no latitude/longitude in the raw file. This is
  expected before the enrichment step and is reflected as 0% coordinate
  validity.
- TheFork uses a native 0-10 rating scale. The report keeps the native value and
  also computes a comparable 0-5 average for cross-source discussion.

## Run

From the repository root, with the project environment:

```powershell
uv run quality-assessment profile
```

Fallback command when `uv` or the project entry point is not available in the
current shell:

```powershell
$env:PYTHONPATH='services'
python -m quality_assessment profile
```

Optional input overrides:

```powershell
$env:PYTHONPATH='services'
python -m quality_assessment profile `
  --google-path data/raw/google_places/restaurants_seed.jsonl `
  --tripadvisor-path data/raw/tripadvisor/tripadvisor_scraper_results.json `
  --thefork-path data/raw/thefork/thefork_milan_restaurants_normalized.json `
  --low-review-threshold 20
```

## Outputs

The profiling command regenerates:

| Output | Description |
|---|---|
| `data/quality/source_quality_metrics.json` | Full structured metrics and anomaly details. |
| `data/quality/source_quality_scores.csv` | Weighted source-level quality score components. |
| `data/quality/field_coverage.csv` | Field-level completeness table. |
| `data/quality/anomalies.csv` | Record-level quality flags. |
| `docs/data-quality-assessment.md` | Generated Markdown report section. |
| `report/tables/source_summary.tex` | LaTeX cross-source summary table. |
| `report/tables/source_quality_scores.tex` | Weighted quality score breakdown. |
| `report/tables/visual_quality_scores.tex` | Pre-integration quality-score bar chart. |
| `report/tables/visual_score_components.tex` | Component-level score bar chart. |
| `report/tables/visual_coverage_heatmap.tex` | Core-field coverage heatmap. |
| `report/tables/visual_anomaly_profile.tex` | Top anomaly classes by source. |
| `report/tables/improvement_actions.tex` | Prioritized data-quality improvement plan. |
| `report/tables/source_comparison.tex` | LaTeX comparative findings table. |
| `report/tables/google_places_detail.tex` | Google Places-specific LaTeX section. |
| `report/tables/tripadvisor_detail.tex` | Tripadvisor-specific LaTeX section. |
| `report/tables/thefork_detail.tex` | TheFork-specific LaTeX section. |
| `report/tables/*_field_coverage.tex` | Full field coverage split by source for the PDF report. |
| `report/tables/field_coverage.tex` | Complete combined LaTeX field coverage table, kept as a generated artifact. |

The files under `docs/data-quality-assessment.md` and `report/tables/` are
generated artifacts. Edit `services/quality_assessment/reporting.py` if the
report structure must change permanently.

## Compile the LaTeX report

The report build script regenerates the quality artifacts and then compiles the
PDF:

```powershell
powershell -ExecutionPolicy Bypass -File .\report\build_report.ps1
```

This compiles:

```text
report/main.pdf
```

The LaTeX entry point is `report/main.tex`; it includes the generated tables and
source-specific sections from `report/tables/`.

## Current metric snapshot

Latest generated values at the time this README was written:

| Source | Records | Quality score | Critical completeness | Spatial readiness | Anomalies |
|---|---:|---:|---:|---:|---:|
| Google Places | 10,808 | 95.14% | 98.15% | 100.00% | 2,937 |
| Tripadvisor | 7,539 | 67.89% | 99.78% | 0.00% | 3,621 |
| TheFork | 1,344 | 97.48% | 99.04% | 99.78% | 195 |

Regenerate the report instead of trusting this table if any raw dataset changes.

## Interpretation notes

- Google Places is currently the strongest geospatial anchor because coordinates
  are complete.
- Tripadvisor must be enriched with latitude and longitude and record-level
  timestamps before geospatial integration and timeliness can be evaluated
  fairly.
- TheFork is already suitable for spatial matching, but contact fields such as
  phone, email, and website have weak coverage.
- Low-review records should not be removed automatically. They should be kept
  but flagged, because they are useful for studying whether sparse data affects
  rating consistency.
- The generated anomaly file is a quality log, not a deletion list. Many flags
  are expected source limitations rather than hard errors.

## Tests and checks

Compile the package:

```powershell
python -m compileall services\quality_assessment tests\quality_assessment
```

Run tests in an environment with development dependencies installed:

```powershell
uv run pytest tests/quality_assessment
```

Fallback command when `uv` is not available:

```powershell
python -m pytest tests/quality_assessment
```

Run formatting/lint checks if the project environment is available:

```powershell
uv run ruff check services/quality_assessment tests/quality_assessment
```

Fallback command when `uv` is not available:

```powershell
python -m ruff check services/quality_assessment tests/quality_assessment
```

## Implementation files

| File | Role |
|---|---|
| `normalization.py` | Missing-value handling, numeric parsing, text normalization, Milan coordinate bounds. |
| `profiler.py` | Source configuration, metric computation, score model, anomaly generation, CSV/JSON outputs. |
| `reporting.py` | Markdown and LaTeX report generation, score tables, improvement actions. |
| `cli.py` | Typer CLI used by the project entry point. |
| `__main__.py` | Lightweight `python -m quality_assessment` fallback. |
