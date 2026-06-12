# ClickHouse Load layer — `load.clickhouse`

Reads the four cleaned and integrated MongoDB collections produced by the transform
pipeline and writes them as **flat** ClickHouse tables ready for analytical queries.

Console script: `dataman-load-clickhouse <target>`

---

## Quick start

```bash
# Prerequisites: transforms and integration must have run first
# (dataman-load all → google-clean / tripadvisor-clean / thefork-clean
#  → dataman-entity-resolve → dataman-unify)

docker compose --profile analytics up -d clickhouse   # start ClickHouse
uv sync --reinstall-package data-management-project   # pick up any code changes
uv run dataman-load-clickhouse all                    # load all four tables
```

Each run is fully idempotent: the loader issues `CREATE TABLE IF NOT EXISTS` followed
by `TRUNCATE TABLE` before inserting, so re-running always converges to the current
MongoDB state with no duplicates.

## Targets

| CLI selector | MongoDB source | ClickHouse table | Natural key |
|---|---|---|---|
| `integrated` | `restaurants_integrated` | `restaurants_integrated` | `integrated_restaurant_id` |
| `clean_google` | `restaurants_clean_google` | `restaurants_clean_google` | `place_id` |
| `clean_tripadvisor` | `restaurants_clean_tripadvisor` | `restaurants_clean_tripadvisor` | `source_url` |
| `clean_thefork` | `restaurants_clean_thefork` | `restaurants_clean_thefork` | `source_id` |
| `all` | all four above | all four above | — |

Load a single target:

```bash
uv run dataman-load-clickhouse integrated
uv run dataman-load-clickhouse clean_google
```

## Configuration

All settings use the `DATAMAN_` env-var prefix and can be placed in `.env`:

| Variable | Default | Description |
|---|---|---|
| `DATAMAN_MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `DATAMAN_MONGO_DB` | `dataman` | MongoDB database name |
| `DATAMAN_CLICKHOUSE_HOST` | `localhost` | ClickHouse server host |
| `DATAMAN_CLICKHOUSE_PORT` | `8123` | HTTP port (used by clickhouse-connect) |
| `DATAMAN_CLICKHOUSE_DB` | `dataman` | ClickHouse database |
| `DATAMAN_CLICKHOUSE_USER` | `default` | ClickHouse user |
| `DATAMAN_CLICKHOUSE_PASSWORD` | _(empty)_ | ClickHouse password |

The `.env.example` in the repo root has these pre-filled for local dev.

## Output — table schemas

All tables use `MergeTree` and are ordered by their natural key. Only the analytical
columns are loaded; heavy nested fields (`reviews`, `opening_hours`, `sources.*`
evidence blocks) are dropped to keep rows slim.

### `restaurants_integrated`

One row per Google-seeded dining restaurant (same scope as `restaurants_integrated` in
MongoDB). Key analytical columns:

| Column | Type | Notes |
|---|---|---|
| `integrated_restaurant_id` | String | `"google:<place_id>"` — primary key |
| `google_place_id` | String | Join key → `restaurants_clean_google.place_id` |
| `tripadvisor_source_url` | String | Join key → `restaurants_clean_tripadvisor.source_url` |
| `thefork_source_id` | String | Join key → `restaurants_clean_thefork.source_id` |
| `canonical_name` / `canonical_city` | String | Authoritative from Google seed |
| `latitude` / `longitude` | Float64 | Authoritative from Google seed |
| `has_google` / `has_tripadvisor` / `has_thefork` | UInt8 | Platform membership |
| `platform_count` | UInt8 | 1–3 |
| `google_rating_5` / `tripadvisor_rating_5` / `thefork_rating_5` | Nullable(Float64) | Per-platform ratings on 0–5 scale |
| `thefork_rating_raw_10` | Nullable(Float64) | TheFork native 0–10 scale |
| `rating_avg_5` | Nullable(Float64) | Mean of available `_5` ratings |
| `rating_range_5` | Nullable(Float64) | max − min spread (key for discrepancy queries) |
| `google_review_count` / `tripadvisor_review_count` / `thefork_review_count` | Nullable(Int64) | |
| `google_photo_count` / `tripadvisor_photo_count` / `thefork_photo_count` | Nullable(Int64) | Per-platform photo counts (visual-content richness) |
| `google_has_website` / `google_has_phone` | UInt8 | Google contact completeness (from `sources.google.contacts`) |
| `tripadvisor_has_website` / `tripadvisor_has_phone` / `tripadvisor_has_email` | UInt8 | Tripadvisor contact completeness |
| `tripadvisor_cuisines` / `thefork_cuisines` | Array(String) | Cuisine labels (platform-native vocabularies, kept separate) |
| `primary_cuisine` | String | First cuisine label, Tripadvisor preferred then TheFork |
| `google_price_level` | String | Google categorical level, e.g. `PRICE_LEVEL_MODERATE` |
| `tripadvisor_price_band` / `tripadvisor_price_tier_level` | String / Nullable(Int64) | Tripadvisor euro band and its 1–4 tier |
| `thefork_avg_price_eur` | Nullable(Int64) | TheFork average price (EUR) |
| `price_tier` | Nullable(Int64) | Normalized cross-platform price tier 1–4 (Tripadvisor tier → Google level → TheFork EUR bins) |
| `google_category_tier` / `google_is_dining` | String / UInt8 | Google dining-relevance classification |
| `price_level` | String | Normalized; list-tie coerced to `"val1 / val2"` |
| `integration_flags` | Array(String) | Audit flags from the integration step |
| `updated_at` | DateTime | From MongoDB `_updated_at` |

The **source join-key columns** (`google_place_id`, `tripadvisor_source_url`,
`thefork_source_id`) are extracted from the nested `sources.*.ids` sub-documents during
projection so the three cleaned tables can be joined back for per-platform detail without
reloading the full nested evidence. The per-platform **photo / contact / cuisine / price**
columns above are likewise lifted from the nested `sources.*` evidence (photo_count,
contacts, cuisines, price, classification), so the most common analytical features are
available directly on `restaurants_integrated` without a join:

```sql
-- Example: join integrated → clean_google for category_tier
SELECT i.canonical_name, i.rating_range_5, g.category_tier
FROM dataman.restaurants_integrated i
LEFT JOIN dataman.restaurants_clean_google g ON i.google_place_id = g.place_id
WHERE i.rating_range_5 > 1
ORDER BY i.rating_range_5 DESC
LIMIT 20;
```

### `restaurants_clean_google`

Flat analytical fields from `restaurants_clean_google` MongoDB. Key columns:
`place_id` (key), `name`, `latitude`/`longitude`, address parts, `city`, `rating`,
`review_count`, `category_tier`, `is_dining`, `is_operational`, `primary_type`,
`types Array(String)`, `price_level`, `has_website`, `has_phone`, `flags Array(String)`.

### `restaurants_clean_tripadvisor`

`source_url` (key), `ta_location_id`, `restaurant_name`, `rating`, `total_review`,
address parts, `latitude`/`longitude`, `has_coordinates`, `price_band`,
`price_tier_level`, `cuisines Array(String)`, `flags Array(String)`.

### `restaurants_clean_thefork`

`source_id` (key), `tf_id`, `restaurant_name`, `latitude`/`longitude`, address parts,
`rating` (native 0–10), `review_count`, `avg_price_eur`, `cuisines Array(String)`,
`dietary_options Array(String)`, `flags Array(String)`.

## Mandatory query examples

ClickHouse is the analytics surface for the project's required queries. After loading:

```sql
-- Restaurants with rating difference > 1 star across platforms
SELECT integrated_restaurant_id, canonical_name, canonical_city,
       google_rating_5, tripadvisor_rating_5, thefork_rating_5,
       rating_range_5
FROM dataman.restaurants_integrated
WHERE rating_range_5 > 1
ORDER BY rating_range_5 DESC;

-- Average rating per platform by city area (postal code)
SELECT canonical_postal_code,
       avg(google_rating_5)       AS avg_google,
       avg(tripadvisor_rating_5)  AS avg_tripadvisor,
       avg(thefork_rating_5)      AS avg_thefork,
       count()                    AS n
FROM dataman.restaurants_integrated
WHERE canonical_postal_code != ''
GROUP BY canonical_postal_code
ORDER BY n DESC;

-- Correlation proxy: review count vs rating variance
SELECT integrated_restaurant_id, canonical_name,
       google_review_count, tripadvisor_review_count, thefork_review_count,
       rating_range_5
FROM dataman.restaurants_integrated
WHERE rating_platform_count >= 2
ORDER BY rating_range_5 DESC;
```

## Implementation details

### Package layout

```
services/load/clickhouse/
  config.py        # ClickHouseLoaderSettings (pydantic-settings, DATAMAN_ prefix)
  schema.py        # CREATE TABLE DDL strings (one per table, {db} placeholder)
  projections.py   # Pure doc→row functions; no I/O, fast unit tests
  targets.py       # TargetSpec frozen dataclass + TARGETS registry + resolve()
  loader.py        # open_mongo / open_clickhouse / load_target orchestration
  cli.py           # Typer CLI (dataman-load-clickhouse)
```

### Design patterns (mirroring `load.mongo`)

- **pydantic-settings config** with `DATAMAN_` prefix, no required fields, `.env` loaded
  automatically.
- **Fail-fast connection helpers**: `open_mongo` pings MongoDB before any work; `open_clickhouse`
  issues `SELECT 1` to verify ClickHouse is reachable. Both import their drivers *inside* the
  function so tests can monkeypatch them.
- **Pluggable `Writer` callable**: production writer calls `ch_client.insert(table, rows,
  column_names=...)`; tests inject a `FakeClickHouseClient` that records calls without I/O.
- **Batch streaming**: rows accumulate in memory up to `BATCH_SIZE = 1000`, then flush — same
  pattern as the Mongo loader.
- **Truncate + reload semantics**: each run issues `TRUNCATE TABLE IF EXISTS` after the `CREATE
  TABLE IF NOT EXISTS`, so re-running is deterministic with no duplicates.
- **`LoadReport` dataclass**: `source`, `collection`, `read`, `inserted`, `skipped`,
  `skipped_reasons` — echoed as indented JSON, same shape as `load.mongo`.

### Projections

`projections.py` contains one pure `project_*(doc) -> dict | None` function per collection.
Responsibilities:
- Extract flat columns; for `restaurants_integrated`, lift source join-keys from
  `sources.*.ids` and per-platform features (photo counts, contact-presence flags,
  cuisines, price band/level, and the normalized `price_tier`) from the nested
  `sources.*` sub-documents.
- Coerce `price_level` string-or-list → `String` (list joined with `" / "`).
- Map Python booleans → `UInt8` (0/1).
- Pass `None` through for `Nullable` columns.
- Return `None` when the natural key is missing (caller skips and counts).

## Testing

```bash
uv run pytest tests/load/clickhouse/test_projections.py tests/load/clickhouse/test_loader.py -v
```

- `test_projections.py` — 19 pure unit tests (flatten correctness, list coercion,
  missing-key skip, absent nested source blocks, missing `_updated_at` fallback).
- `test_loader.py` — 10 tests with mongomock source + `FakeClickHouseClient` (happy path,
  missing-key skip, truncate+reload idempotency, batch flushing, all four targets).
- `test_integration.py` — real MongoDB + ClickHouse; auto-skips when either is unreachable.
  Run explicitly after `docker compose --profile analytics up -d clickhouse`.
