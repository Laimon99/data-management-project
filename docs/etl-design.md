# ETL & load-layer design

Status: **design only** — this document records decisions made while standing up the
storage infrastructure (`docker-compose.yml`, see [`dev-guide.md`](dev-guide.md)). The
loading/ETL code described here is **not built yet**; it is the next step.

Related docs: [`storage-design.md`](storage-design.md) (DBMS evaluation),
[`../specs/data-storage-layer.md`](../specs/data-storage-layer.md) (original spec).

## Why this doc exists

We deliberately split the storage work into two steps:

1. **Storage infrastructure (done):** Docker services for the databases — MongoDB now,
   ClickHouse scaffolded behind the `analytics` profile.
2. **Load / ETL layer (this doc, next step):** the code that moves data
   `raw files -> MongoDB` and later `MongoDB -> ClickHouse`.

Keeping them separate avoids prematurely committing to a load design that should serve
**all three sources**, not just Google Places.

## Locked decisions

- **MongoDB = document system of record.** Holds the raw nested seed and (later) raw
  per-platform records. Runs on every `docker compose up`.
- **ClickHouse 26.3 (LTS) = columnar analytics engine.** Hosts the integrated ratings
  table and the mandatory analytical queries. Behind the `analytics` compose profile;
  off by default. (Engine choice follows `storage-design.md`'s recommendation; the spec
  locked the columnar pick as ClickHouse.)
- **Local dev Mongo runs without auth** (localhost only) to minimise beginner friction;
  auth hardening is out of scope until deployment.

## The core architectural decision: load code is its own layer

Today, MongoDB persistence lives **inside an extractor**:
`services/google_places_api_extract/storage.py` contains `MongoSeedStore` and a
`seed_store_backend = "mongo"` switch. That is a **load concern that leaked into an
extract service**, and it creates an asymmetry:

| Source       | Extractor                                | Mongo store today |
|--------------|------------------------------------------|-------------------|
| Google Places| `services/google_places_api_extract`     | yes (`MongoSeedStore`) |
| Tripadvisor  | `services/tripadvisor_scraper_extract`   | none |
| TheFork      | `services/thefork_scraper_extract`       | none |

**Decision:** the load/ETL layer is a **separate package** (e.g. `services/storage/` or
`services/loaders/`). Extractors stay extraction-only and emit raw output; the load
layer is the single place that writes into MongoDB.

- **Relocate** `MongoSeedStore` (and the `seed_store_backend=mongo` path) out of the
  Google Places extractor into that shared layer when it is built.
- **`SeedDoc`** (`services/google_places_api_extract/schema.py`) is defensibly the
  *extractor's output contract* and can stay where it is; revisit if a canonical
  storage schema diverges from it.
- Bring Tripadvisor and TheFork to parity: each source's raw output flows into its own
  Mongo collection through the same load layer.

## Target collections / tables

Mongo raw collections and the integrated ClickHouse table follow the "Future storage
shape" already sketched in the root `README.md`:

- `restaurants_raw_google` — seed + raw Place Details.
- `restaurants_raw_tripadvisor` — raw scraped payload.
- `restaurants_raw_thefork` — raw scraped payload.
- `restaurants_integrated` (ClickHouse) — unified per-restaurant ratings + coordinates,
  feeding the mandatory queries (rating difference > 1 star, avg rating by area, …).

## Deferred design sketch (to build next)

- **A `services/storage/` package** registered in `pyproject.toml`
  (`[project.scripts]`, wheel `packages`, ruff `known-first-party`), with its own
  lightweight settings (`DATAMAN_` prefix, Mongo + ClickHouse fields only — it must
  **not** require the Google API key that the extractor's `Settings` demands).
- **A two-runtime loader, same code:**
  - **Host (default):** `uv run ...` talking to `localhost` — the everyday path.
  - **Container (optional):** built from a uv-based `docker/loader/Dockerfile`
    (Python 3.11, **no Playwright browsers**), talking to services by name
    (`mongodb://mongo:27017`), behind a `tools` compose profile for an all-in-Docker /
    CI bring-up. This Dockerfile is also the future home of the `mongo -> clickhouse`
    ETL.
- **`load-seed`:** read `data/raw/google_places/restaurants_seed.jsonl`, validate each
  line with `SeedDoc`, and **idempotently upsert** into Mongo keyed on `place_id`
  (re-running must not duplicate). Skip and report malformed lines; fail with a clear
  message if the seed file is missing.
- **Per-platform loaders** for Tripadvisor and TheFork raw output.
- **`mongo -> clickhouse` ETL** producing `restaurants_integrated` after entity
  resolution.
- **Tests** under `tests/storage/` using `mongomock` (already a dev dependency): happy
  path, idempotency, malformed-line handling, missing-file handling, config wiring.
