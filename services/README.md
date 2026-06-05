# services/

Services are grouped by **pipeline stage** — `extract/`, `load/`, `transform/` — with one self-contained Python package per source under each. Each package has its own CLI entry point, internal modules, and co-located docs. The stage directories are PEP 420 namespace packages, so imports read as `extract.google_places_api`, `load.mongo`, `transform.tripadvisor_geocode`.

```
services/
  extract/   google_places_api/  tripadvisor_scraper/  thefork_scraper/
  load/      mongo/
  transform/ tripadvisor_geocode/
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

- Writes the normalized dataset to `data/raw/thefork/thefork_milan_restaurants_normalized.json` (plus partial-progress and validation-report files).
- Listing data is reliable; detail enrichment can be rate-limited (see `docs/antibot-comparison.md`). Supports resume, proxy rotation (burn-through / round-robin), and a calibration mode to size proxy needs.

```bash
uv run thefork-scraper-extract                       # full listing + detail scrape
uv run thefork-scraper-extract --resume-detail --proxy-list proxies.txt --proxy-round-robin
uv run thefork-merge-outputs run_a.json run_b.json --output data/raw/thefork/thefork_milan_restaurants_normalized.json
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

### `transform/tripadvisor_geocode` — Geocoding enrichment
Adds `latitude`/`longitude` to raw Tripadvisor records by geocoding their address strings via Nominatim/OpenStreetMap (`geopy`, free, no key). Feeds proximity blocking in entity resolution and the geographic queries.

```bash
uv run tripadvisor-geocode-enrich            # full run (defaults under data/raw/tripadvisor/)
uv run tripadvisor-geocode-enrich --limit 20 # quick test slice
```

See `transform/tripadvisor_geocode/README.md` for details and coverage notes.

---

## Planned services (not yet implemented)

| Service | Stage | Description |
|---|---|---|
| `transform/entity_resolution` | 3 | Record linkage: proximity blocking + name/address similarity → match/no-match/uncertain |
| `transform/unified_dataset` | 4 | Joins resolved platform records into a single ratings table |
| `transform/quality_assessment` | 5 | Completeness, consistency, uniqueness, and timeliness metrics; before/after improvement |

## Conventions

- Each service is a `uv` entry point defined in `pyproject.toml`.
- No cross-service imports — services communicate through files in `data/raw/`.
- Service-specific documentation, schema files, and design notes live inside the service directory alongside the code.
