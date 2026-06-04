# services/

One directory per pipeline stage/source. Each service is a self-contained Python package with its own CLI entry point, internal modules, and co-located docs.

## Implemented services

### `google_places_api_extract` — Stage 1: Seed Acquisition
Collects the canonical list of Milan restaurants from the Google Places API (New).

- **Mode `list`** — tiles the city into overlapping search circles, pages through Nearby Search results, deduplicates by `place_id`, and appends to `data/raw/google_places/restaurants_seed.jsonl`.
- **Mode `detail`** — fetches full Place Details for each `place_id` and merges enriched fields (rating, review count, opening hours, service flags, etc.) into the same JSONL record.
- Checkpointing allows interrupted runs to resume.

```bash
uv run google-places-api-extract --mode list
uv run google-places-api-extract --mode detail
```

See `google_places_api_extract/README.md` for full CLI reference and schema.

---

### `tripadvisor_scraper_extract` — Stage 2: Tripadvisor Collection
Playwright-based scraper that collects restaurant ratings and review counts from Tripadvisor for the Milan area.

- Writes raw results to `data/raw/tripadvisor/tripadvisor_scraper_results.json`.
- Maintains a checkpoint file so partial runs can be resumed.

```bash
uv run tripadvisor-scraper-extract
```

See `tripadvisor_scraper_extract/tripadvisor-scraper-extract.md` for implementation notes and scraper logic.

---

### `thefork_scraper_extract` — Stage 2: TheFork Collection
Playwright-based scraper that collects Milan restaurant listings from TheFork, then optionally enriches each record from its detail page.

- Writes the normalized dataset to `data/raw/thefork/thefork_milan_restaurants_normalized.json` (plus partial-progress and validation-report files).
- Listing data is reliable; detail enrichment can be rate-limited (see `docs/antibot-comparison.md`). Supports resume, proxy rotation (burn-through / round-robin), and a calibration mode to size proxy needs.

```bash
uv run thefork-scraper-extract                       # full listing + detail scrape
uv run thefork-scraper-extract --resume-detail --proxy-list proxies.txt --proxy-round-robin
uv run thefork-merge-outputs run_a.json run_b.json --output data/raw/thefork/thefork_milan_restaurants_normalized.json
```

See `thefork_scraper_extract/README.md` for the full CLI reference (proxy, calibration, merge) and `SCRAPER_SPEC.md` for the extraction spec.

---

## Planned services (not yet implemented)

| Service | Stage | Description |
|---|---|---|
| `entity_resolution` | 3 | Record linkage: proximity blocking + name/address similarity → match/no-match/uncertain |
| `unified_dataset` | 4 | Joins resolved platform records into a single ratings table |
| `quality_assessment` | 5 | Completeness, consistency, uniqueness, and timeliness metrics; before/after improvement |

## Conventions

- Each service is a `uv` entry point defined in `pyproject.toml`.
- No cross-service imports — services communicate through files in `data/raw/`.
- Service-specific documentation, schema files, and design notes live inside the service directory alongside the code.
