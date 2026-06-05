# Geocoding enrichment — Tripadvisor (transform)

Adds `latitude` / `longitude` to raw Tripadvisor records by geocoding their
address strings with **Nominatim / OpenStreetMap** (via `geopy`). Free, no API
key. Coordinates feed proximity blocking in entity resolution and the
geographic queries on the unified dataset.

> Ported and adapted from work by **Edoardo** on the
> `tripadvisor-geocoding-enrichment` branch (relocated into the `transform`
> stage, parametrised paths, English/ruff-clean, added a `--limit` test slice).

## Pipeline position

```
extract/tripadvisor_scraper  ->  data/raw/tripadvisor/tripadvisor_scraper_results.json
                                        │
                          transform/tripadvisor_geocode  (this service)
                                        ▼
                 data/raw/tripadvisor/tripadvisor_scraper_results_geocoded.json
```

## Usage

```bash
uv sync
# Full run (defaults read/write under data/raw/tripadvisor/). ~7.5k records at
# >=1 req/s -> roughly 2.5h, per Nominatim's rate limit.
uv run tripadvisor-geocode-enrich

# Quick test slice (no full run):
uv run tripadvisor-geocode-enrich --limit 20

# Custom paths / tuning:
uv run tripadvisor-geocode-enrich -i in.json -o out.json --delay 1.2 --timeout 10
```

The geocoded output is **gitignored** (large, regenerable) — run the command to
produce it locally rather than committing it.

## Output

Each record keeps its original keys, with `latitude`/`longitude` inserted right
after `address`. Missing/`NaN` addresses are skipped with `NaN` coordinates;
addresses Nominatim can't resolve also get `NaN`. The command prints a summary:

```json
{ "total": 7539, "found": 6327, "not_found": 1146, "skipped": 66 }
```

Reference coverage from the original run: **83.9% found** (6,327/7,539). The
~15% miss rate reflects OSM's limited coverage of recent/informal venues and is
acceptable for mapping, clustering, and spatial joins.

## Notes

- `--delay` must stay `>= 1s` to respect the [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/);
  a descriptive `user_agent` is sent (configurable via `DATAMAN_GEOCODE_USER_AGENT`).
- Settings (`delay_seconds`, `timeout`, `max_retries`, `user_agent`) are
  overridable via `DATAMAN_GEOCODE_*` env vars — see `config.py`.
- `--delay` is validated to be `>= 1s`; sub-second values are rejected.
- The output is written atomically (temp file + `os.replace`), so a crash can't
  leave a truncated file. There is **no mid-run resume/checkpoint**, though: the
  full input is processed in one pass, so a crash means re-running from the start.
