# services/

Services are grouped by **pipeline stage** — `extract/`, `load/`, `transform/` — with one self-contained Python package per source under each. Each package has its own CLI entry point, internal modules, and co-located docs. The stage directories are PEP 420 namespace packages, so imports read as `extract.google_places_api`, `load.mongo`, `transform.tripadvisor_clean`.

```
services/
  extract/   google_places_api/  tripadvisor_scraper/  thefork_scraper/
  load/      mongo/  clickhouse/
  transform/ google_clean/  tripadvisor_clean/  thefork_clean/
             entity_resolution/  entity_resolution_llm/
             llm_matching_pipeline/  unified_dataset/
  quality_assessment/  integration_assessment/
  analysis/  (with analysis/queries/ SQL)
```

## Implemented services

### `extract/google_places_api` — Stage 1: Seed Acquisition
Collects the canonical list of Milan restaurants from the Google Places API (New).

- **Mode `list`** — tiles the city into overlapping search circles, pages through Nearby Search results, deduplicates by `place_id`, and appends to `data/raw/google_places/restaurants_seed.jsonl`.
- **Mode `detail`** — fetches full Place Details for each `place_id` and merges enriched fields (rating, review count, opening hours, service flags, etc.) into the same JSONL record.
- Checkpointing allows interrupted runs to resume.

```bash
uv run google-places-api-extract --mode list
uv run google-places-api-extract --mode detail
```

See `extract/google_places_api/README.md` for full CLI reference and schema.

---

### `extract/tripadvisor_scraper` — Stage 2: Tripadvisor Collection
Playwright-based scraper that collects restaurant ratings and review counts from Tripadvisor for the Milan area.

- Writes raw results to `data/raw/tripadvisor/tripadvisor_scraper_results.json`.
- Maintains a checkpoint file so partial runs can be resumed.

```bash
uv run tripadvisor-scraper-extract
```

See `extract/tripadvisor_scraper/README.md` for implementation notes and scraper logic.

---

### `extract/thefork_scraper` — Stage 2: TheFork Collection
Playwright-based scraper that collects Milan restaurant listings from TheFork, then optionally enriches each record from its detail page.

- Writes the enriched dataset to `data/raw/thefork/thefork_milan_restaurants_enriched.json` (plus partial-progress and validation-report files).
- Listing data is reliable; detail enrichment can be rate-limited (see `docs/antibot-comparison.md`). Supports resume, proxy rotation (burn-through / round-robin), and a calibration mode to size proxy needs.

```bash
uv run thefork-scraper-extract                       # full listing + detail scrape
uv run thefork-scraper-extract --resume-detail --proxy-list proxies.txt --proxy-round-robin
uv run thefork-merge-outputs run_a.json run_b.json --output data/raw/thefork/thefork_milan_restaurants_enriched.json
```

See `extract/thefork_scraper/README.md` for the full CLI reference (proxy, calibration, merge) and `SCRAPER_SPEC.md` for the extraction spec.

---

### `load/mongo` — Load layer
Raw passthrough loader that idempotently upserts the extractor files from `data/raw/` into MongoDB (`restaurants_raw_{google,tripadvisor,thefork}`), keyed on each source's natural id.

```bash
docker compose up -d mongo
uv run dataman-load all
```

See `load/mongo/README.md` for the source registry and load semantics.

---

### `transform/google_clean` — Clean + normalize + relevance-flag (Mongo → Mongo)
The single Google transform. Reads `restaurants_raw_google`, projects the lean fields out of the heavy raw `details` blob, normalizes name/city, lifts structured address parts from `addressComponents`, copies the authoritative coordinates (**never** re-geocoded), and flags dining relevance (`is_dining` / `category_tier`) so non-dining noise (gas stations, supermarkets, hotels) can be excluded from matching. Upserts into `restaurants_clean_google`. Idempotent, with full-run stale-delete convergence.

```bash
uv run google-clean                 # full run
uv run google-clean --limit 20      # quick test slice
```

See `transform/google_clean/README.md` and `transform/google_clean/clean-dataset-schema.md`.

---

### `transform/tripadvisor_clean` — Clean + structure + geocode + flag (Mongo → Mongo)
The single Tripadvisor transform. Reads `restaurants_raw_tripadvisor`, type-repairs the Italian display strings (`"5,0"`→float, `"(1.234 recensioni)"`→int, `NaN`→`null`), normalizes name/address/contacts, structures the 1NF-violation fields (`price_range`→tier, `cuisine_type`→`cuisines`, `working_days_hours`→`opening_hours`, `review`→slim capped `reviews`), lifts `ta_location_id`, geocodes the cleaned address via Nominatim/OpenStreetMap (`geopy`, free, no key) as a sub-step, and derives per-record quality flags. Upserts into `restaurants_clean_tripadvisor`. Idempotent, resumable, with full-run stale-delete convergence.

```bash
uv run tripadvisor-clean            # full run (clean + structure + geocode)
uv run tripadvisor-clean --limit 20 # quick test slice
uv run tripadvisor-clean --skip-geocode  # fast clean-only pass
```

See `transform/tripadvisor_clean/README.md`, `clean-dataset-schema.md`, and `drop-policy.md`.

---

### `transform/thefork_clean` — Parse + structure + flag (Mongo → Mongo)
The single TheFork transform. Reads `restaurants_raw_thefork` (already typed and geocoded), so it does **parse + structure + flag**, not type-repair or geocoding: parses the 1NF-violation fields (`price_range`→`avg_price_eur`, `cuisine_type`→`cuisines`+`dietary_options`, `discount`→`discount_pct`, hours→`opening_hours`), normalizes name/city/address, lifts `tf_id`, slims reviews, and derives count-only flags. Upserts into `restaurants_clean_thefork`. Idempotent, with full-run stale-delete convergence.

```bash
uv run thefork-clean                # full run
uv run thefork-clean --limit 20     # quick test slice
```

See `transform/thefork_clean/README.md`, `transform/thefork_clean/clean-dataset-schema.md`,
and `extract/thefork_scraper/eda-report.md`.

---

### `transform/entity_resolution` — Stage 3: Deterministic record linkage
Google-anchored entity resolution. Generates auditable Google × Tripadvisor and
Google × TheFork candidate pairs in `entity_resolution_candidates`, with deterministic
`label`, score components, thresholds, chain flags, and `llm_label=null`.

```bash
uv run dataman-entity-resolve --replace-destination
```

See `transform/entity_resolution/README.md`.

---

### `transform/entity_resolution_llm` — Stage 3b: LLM adjudication
Reviews `label == "UNCERTAIN"` candidate groups from `entity_resolution_candidates` and
updates the same documents with `llm_label` plus audit metadata. Supports `dry-run`,
offline `mock`, and real OpenAI modes.

```bash
uv run dataman-er-llm --mode dry-run --limit 10
uv run dataman-er-llm --mode mock --limit 10
DATAMAN_OPENAI_API_KEY=... uv run dataman-er-llm --mode openai --apply
```

See `transform/entity_resolution_llm/README.md`.

---

### `transform/unified_dataset` — Stage 4: Unified analytical dataset
Selects one-to-one resolved Google x Tripadvisor and Google x TheFork links, then writes
the Google-seeded integrated ratings collection with nested source evidence and
top-level analytical fields.

```bash
uv run dataman-unify --dry-run
uv run dataman-unify --replace-destination
```

See `transform/unified_dataset/README.md` and
`transform/unified_dataset/integrated-dataset-schema.md`.

---

### `transform/llm_matching_pipeline` — Stage 3b+4: One-command LLM pipeline
Convenience runner for the LLM matching branch. It runs LLM adjudication and then
rebuilds `entity_resolution_links` plus `restaurants_integrated`. It assumes the clean
collections and `entity_resolution_candidates` already exist.

Complete Windows/PowerShell run from Mongo off:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_llm_matching_pipeline.ps1 `
  -Mode dry-run -Limit 10
powershell -ExecutionPolicy Bypass -File .\scripts\run_llm_matching_pipeline.ps1 `
  -Mode mock -Limit 10 -Apply
$env:DATAMAN_OPENAI_API_KEY="..."
powershell -ExecutionPolicy Bypass -File .\scripts\run_llm_matching_pipeline.ps1 `
  -Mode openai -Limit 10 -Apply `
  -OutputJsonl data/quality/llm_er_results_sample.jsonl
powershell -ExecutionPolicy Bypass -File .\scripts\run_llm_matching_pipeline.ps1 `
  -Mode openai -NoLimit -Apply `
  -OutputJsonl data/quality/llm_er_results.jsonl
```

Lower-level commands, when Mongo and prepared collections already exist:

```bash
docker compose up -d mongo
uv run dataman-llm-pipeline --mode dry-run --limit 10
uv run dataman-llm-pipeline --mode mock --limit 10 --apply
DATAMAN_OPENAI_API_KEY=... uv run dataman-llm-pipeline --mode openai --apply
```

With `--apply`, the command writes `llm_label` decisions back to
`entity_resolution_candidates`. Run `dataman-unify --replace-destination`
afterwards to rebuild the final dataset.

See `transform/llm_matching_pipeline/README.md`.

---

### `quality_assessment` — Stage 5: Data Quality Assessment
Profiles the raw Google Places, Tripadvisor, and TheFork datasets and generates
report-ready quality artifacts: structured metrics, weighted quality scores,
field coverage, anomalies, Markdown notes, and LaTeX tables.

```bash
uv run quality-assessment
```

Outputs are written under `data/quality/`, `docs/data-quality-assessment.md`,
and `report/pre_integration/tables/`.

The full PDF report can be regenerated from the repository root with:

```bash
powershell -ExecutionPolicy Bypass -File ./report/pre_integration/build_report.ps1
```

---

### `integration_assessment` — Stage 5b: Post-Integration Assessment
Measures entity-resolution classifier error, one-to-one link survival, and
Tripadvisor geocoding error against hand-labeled gold CSVs. Runs after
`dataman-unify`.

```bash
uv run integration-assessment
uv run integration-assessment \
  --in-calibration-gold-csv data/quality/entity_resolution_calibration_normal.csv \
  --in-calibration-gold-csv data/quality/entity_resolution_calibration_chains.csv \
  --gold-csv data/quality/my_out_of_sample_gold.csv
```

Outputs: `data/quality/integration_assessment/`, `docs/post-integration-assessment.md`,
`report/post_integration/tables/*.tex`. See `integration_assessment/README.md`.

---

### `analysis` — Stage 6: Analysis / research questions
The analysis stage backing the eleven research questions. It ships the externalized SQL in
`analysis/queries/` (`q0`–`q11`) and shared helpers — `notebook.py` (the `from
analysis.notebook import *` setup imported by every notebook, with `run`/`publish`),
`export.py` (CSV/LaTeX writers), `geo.py` (Duomo-distance / neighbourhood helpers), and
`config.py` (read-only ClickHouse client). The `notebooks/q00…q11` import these to query
ClickHouse and publish per-question CSV/LaTeX tables + chart PNGs into `report/` for the
final report (`report/overleaf`, `report/presentation`).

`dump.py` backs a separate convenience CLI that dumps whole ClickHouse tables to CSV/Parquet:

```bash
uv run dataman-analysis-export            # → data/analysis_export/restaurants_integrated.csv
uv run dataman-analysis-export all --format parquet
```

See `analysis/README.md` and `analysis/queries/README.md`.

---

## Conventions

- Each service is a `uv` entry point defined in `pyproject.toml`.
- No cross-service imports — services communicate through files in `data/raw/`.
- Service-specific documentation, schema files, and design notes live inside the service directory alongside the code.
