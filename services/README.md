# services/

Services are grouped by **pipeline stage** — `extract/`, `load/`, `transform/` — with one self-contained Python package per source under each. Each package has its own CLI entry point, internal modules, and co-located docs. The stage directories are PEP 420 namespace packages, so imports read as `extract.google_places_api`, `load.mongo`, `transform.tripadvisor_clean`.

```
services/
  extract/   google_places_api/  tripadvisor_scraper/  thefork_scraper/
  load/      mongo/
  transform/ google_clean/  tripadvisor_clean/  thefork_clean/
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

### `quality_assessment` — Stage 5: Data Quality Assessment
Profiles the raw Google Places, Tripadvisor, and TheFork datasets and generates
report-ready quality artifacts: structured metrics, weighted quality scores,
field coverage, anomalies, Markdown notes, and LaTeX tables.

```bash
uv run quality-assessment
```

Outputs are written under `data/quality/`, `docs/data-quality-assessment.md`,
and `report/tables/`.

The full PDF report can be regenerated from the repository root with:

```bash
powershell -ExecutionPolicy Bypass -File ./report/build_report.ps1
```

---

## Planned services (not yet implemented)

| Service | Stage | Description |
|---|---|---|
| `transform/entity_resolution` | 3 | Record linkage: proximity blocking + name/address similarity → match/no-match/uncertain |
| `transform/unified_dataset` | 4 | Joins resolved platform records into a single ratings table |

## Conventions

- Each service is a `uv` entry point defined in `pyproject.toml`.
- No cross-service imports — services communicate through files in `data/raw/`.
- Service-specific documentation, schema files, and design notes live inside the service directory alongside the code.
