# Spec for storage-load-layer
branch: feature/storage-load-layer

## Summary

This feature builds the **Load layer** of an **ELT** (Extract → Load → Transform)
pipeline: a standalone Python package, `services/load/mongo/`, whose single job is to move
the already-extracted raw files from `data/raw/` into **MongoDB**, with **no
transformation**. The data is loaded as-is ("raw passthrough") so that all parsing,
normalization, deduplication, spatial enrichment (e.g. geopy geocoding), entity
resolution, and analytics happen *later*, as separate Transform stages operating on
MongoDB — not at load time.

This is deliberately scoped to **Load only**. It is the bridge between work that is
already done (the three extractors) and work that comes next (Transform / Integrate /
Query in Mongo, and an optional future `mongo → clickhouse` analytics sink).

### Why this layer, and why now

- The three source extractors are complete and have produced raw files on disk:
  - **Google Places** — `data/raw/google_places/restaurants_seed.jsonl`
    (~10,808 records, JSON Lines, ~249 MB).
  - **Tripadvisor** — `data/raw/tripadvisor/tripadvisor_scraper_results.json`
    (7,539 records, single JSON array, ~49 MB).
  - **TheFork** — `data/raw/thefork/thefork_milan_restaurants_enriched.json`
    (1,344 records, single JSON array, ~5 MB).
- MongoDB already runs as Docker infrastructure (`docker-compose.yml`, service
  `mongo:7` on `localhost:27017`). It is the locked **document system of record** for
  raw data (see `docs/etl-design.md`, `docs/storage-design.md`).
- Today, the only MongoDB write path (`MongoSeedStore` in
  `services/extract/google_places_api/storage.py`) lives *inside* an extractor and only
  serves Google. `docs/etl-design.md` already decided the load concern must become its
  own shared package so all three sources reach MongoDB symmetrically through one place.

### Architectural decisions locked during brainstorming

These were agreed before writing this spec and constrain the implementation:

1. **ELT, not ETL.** The Load step performs a **pure raw passthrough**. No pydantic
   validation, no field parsing, no schema coercion at load time. Records enter MongoDB
   exactly as they appear in the raw files (plus a small amount of load *metadata* — see
   below). This keeps the raw collections faithful to the source and defers all
   transformation to dedicated downstream stages.
2. **MongoDB is the whole pipeline for now.** Load → Transform → Integrate all happen in
   MongoDB with Python. **ClickHouse is an optional, future downstream sink** (a
   `mongo → clickhouse` loader for analytics / research-question queries) and is
   explicitly **out of scope** for this feature.
3. **The Load layer is its own package** (`services/load/mongo/`). Extractors remain
   extraction-only. This package must **not** depend on any extractor package and must
   **not** require the Google Places API key that the extractor's `Settings` demands.
4. **Generic, config-driven loader** — a single loader implementation parameterized by a
   per-source registry, rather than three bespoke loaders. The only real differences
   between sources are: file path, on-disk format (JSON Lines vs single JSON array),
   the natural key field, and the destination collection. Those are *data*, expressed in
   a registry — not duplicated code.
5. **Natural key becomes Mongo `_id`.** Each source has a verified-unique, non-null
   natural key. Using it as the document `_id` gives idempotent upserts and uniqueness
   "for free" — re-running a load must never create duplicates.

### Source registry (the heart of the configuration)

| Source       | Raw file                                              | Format      | Natural key (→ `_id`) | Destination collection         |
|--------------|-------------------------------------------------------|-------------|-----------------------|--------------------------------|
| `google`     | `data/raw/google_places/restaurants_seed.jsonl`       | JSON Lines  | `place_id`            | `restaurants_raw_google`       |
| `tripadvisor`| `data/raw/tripadvisor/tripadvisor_scraper_results.json`| JSON array  | `source_url`          | `restaurants_raw_tripadvisor`  |
| `thefork`    | `data/raw/thefork/thefork_milan_restaurants_enriched.json` | JSON array | `source_id`         | `restaurants_raw_thefork`      |

Key uniqueness/non-nullness was verified against the current raw files
(google `place_id`: 10,808 unique; tripadvisor `source_url`: 7,539 unique, 0 null;
thefork `source_id`: 1,344 unique, 0 null).

## Functional Requirements

### Package & configuration
- Create a new package `services/load/mongo/` (`__init__.py`, `config.py`, `sources.py`,
  `loader.py`, `cli.py`, `__main__.py`).
- Provide a settings object (e.g. `LoaderSettings`) using the project's existing
  pydantic-settings convention with the **`DATAMAN_` env prefix**, exposing only:
  - `mongo_uri` (default `mongodb://localhost:27017`),
  - `mongo_db` (default `dataman`),
  - and any per-source path/collection overrides needed.
  It must **not** define or require the Google Places API key.
- Define a **source registry** in `sources.py` describing each of the three sources:
  source name, raw file path, format (`jsonl` | `json_array`), natural key field, and
  destination collection name (matching the table above).
- Register the package in `pyproject.toml` so it ships and lints like the others:
  add a `[project.scripts]` console entry point (`dataman-load`), include the package in
  the wheel `packages` list, and add it to ruff `known-first-party`.

### Loading behavior (raw passthrough)
- Implement **one generic loader** that, given a registry entry, reads its records and
  upserts them into the destination MongoDB collection.
- **Read by format:**
  - `jsonl`: stream **line by line** (the Google file is ~249 MB and must never be fully
    materialized in memory).
  - `json_array`: load the array (the array files are ≤49 MB, acceptable to read whole).
- For each record:
  - Set the MongoDB document **`_id` to the value of the source's natural key field**.
  - Attach minimal **load metadata** without altering source fields. At minimum:
    `_loaded_at` (UTC timestamp) and `_source_file` (the file the record came from).
    These underscored keys are clearly load metadata, not source data.
  - Otherwise store the record **exactly as parsed** — no field renaming, type coercion,
    or schema validation.
- **Idempotent upsert keyed on `_id`** (replace-or-insert). Re-running a load over the
  same file must converge to the same collection contents with **no duplicates**.
- After each source load, **report a summary**: counts of records read, inserted/updated
  (upserted), and skipped (with reasons).

### CLI
- Expose a console command `dataman-load` accepting a positional source selector:
  `google`, `tripadvisor`, `thefork`, or `all`.
- `all` loads every registered source in turn, printing a per-source summary and a final
  total.
- Exit non-zero if a requested source's raw file is missing (see edge cases).

### Boundaries & non-interference
- The package must run on the **host** via `uv run dataman-load ...` against
  `localhost:27017` (the everyday path).
- It must **not** import from or modify the extractor packages. The existing
  `MongoSeedStore` inside the Google extractor is left untouched in this feature (it is
  superseded by this layer and can be deprecated separately).

## Possible Edge Cases
- **Missing raw file** for a requested source → fail fast with a clear, actionable error
  message naming the expected path; non-zero exit. For `all`, surface which source is
  missing.
- **Malformed JSON line** (jsonl) → skip that line, count it as skipped, log enough to
  locate it (e.g. line number), and continue. A few bad lines must not abort the load.
- **Record missing the natural key field** (or key is null/empty) → cannot form a stable
  `_id`; skip and count as skipped with a reason, rather than letting Mongo auto-assign
  an ObjectId (which would break idempotency).
- **Duplicate keys within the same file** → last-write-wins via upsert; the final state
  is deterministic and contains one document per key.
- **Re-running a load** (idempotency) → no duplicate documents; existing documents are
  replaced with the latest raw content (load metadata refreshed).
- **Large JSONL file** (~249 MB) → must be streamed; loading it must not exhaust memory.
- **Empty raw file** → load completes with a zero-count summary, not an error.
- **MongoDB unreachable** → fail with a clear connection error (do not hang silently).
- **Unknown source selector** passed to the CLI → clear usage error listing valid
  choices; non-zero exit.

## Acceptance Criteria
- `uv run dataman-load google` populates `restaurants_raw_google` with one document per
  `place_id`, each carrying `_id == place_id`, the original fields verbatim, and load
  metadata.
- `uv run dataman-load tripadvisor` and `uv run dataman-load thefork` do the same for
  their collections, keyed on `source_url` and `source_id` respectively.
- `uv run dataman-load all` loads all three sources and prints per-source and total
  summaries.
- Running any load **twice** results in the **same document count** as running it once
  (idempotency), and a re-run reports updates rather than inserts.
- Document counts after a fresh load match the source record counts minus any skipped
  records, and the skip count is reported.
- The package imports and runs **without** a Google Places API key configured.
- A missing raw file produces a clear error and non-zero exit; a malformed jsonl line is
  skipped and reported without aborting the run.
- `pyproject.toml` exposes the `dataman-load` script, includes the package in the wheel,
  and lists it under ruff `known-first-party`; `uv run pre-commit run --all-files`
  passes on the new code.

## Open Questions
- Should a `--drop` (or `--reset`) flag be offered to clear a collection before loading?
  (Default behavior is non-destructive idempotent upsert; a reset flag is a convenience,
  not a requirement.)
- Should load metadata also capture a content hash or the source `scraped_at`/
  `seed_collected_at` to support later "what changed" diffing, or is `_loaded_at` +
  `_source_file` sufficient for now? (Leaning sufficient — keep it minimal.)
- Do we want a non-default `tools` Docker profile / loader image now, or defer it?
  (Brainstorming leaned **host-only for now**; container runtime deferred.)

## Out of Scope
- Any **Transform** stage: parsing Italian-locale strings, name/address normalization,
  deduplication, **spatial enrichment / geopy geocoding**, and record linkage / entity
  resolution. These operate on MongoDB *after* this layer and are separate features.
- The **integrated** collection (`restaurants_integrated`) and the mandatory analytical
  queries.
- **ClickHouse** and any `mongo → clickhouse` loader (optional future analytics sink).
- Removing or refactoring the existing `MongoSeedStore` from the Google extractor.
- MongoDB authentication / production hardening (local dev runs auth-free, localhost
  only, per `docs/etl-design.md`).
- A containerized loader runtime (`docker/loader/Dockerfile`, `tools` compose profile).

## Feature Testing Guidelines
Create test file(s) under `tests/load/mongo/` using `mongomock` (already a dev dependency).
Keep tests meaningful but lightweight; cover:
- **Happy path** — loading a small fixture for each format (jsonl and json_array) creates
  the expected number of documents in the right collection, with `_id` set to the natural
  key and the original fields preserved verbatim.
- **Load metadata** — loaded documents carry `_loaded_at` and `_source_file`, and these
  do not clobber any source field.
- **Idempotency** — loading the same fixture twice yields the same document count (no
  duplicates) and the second run upserts/replaces rather than inserting anew.
- **Malformed jsonl line** — a bad line is skipped and counted, and the rest of the file
  still loads.
- **Missing natural key** — a record lacking the key (or with a null/empty key) is
  skipped and counted, not assigned an auto-generated `_id`.
- **Missing file** — requesting a source whose raw file does not exist raises a clear
  error / non-zero exit.
- **Config wiring** — the settings object reads `DATAMAN_`-prefixed env vars and does not
  require the Google API key; the source registry resolves the expected paths,
  key fields, and collection names.
