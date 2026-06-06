# Spec for tripadvisor-elt-transform
branch: feature/tripadvisor-elt-transform

## Summary

This feature establishes the **Transform (T) layer of the ELT pipeline** for the
Tripadvisor source, and in doing so sets the canonical pattern that the other two
sources (Google Places, TheFork) will later copy.

Today the project is **E** and **L** complete for Tripadvisor: the Playwright scraper
(`services/extract/tripadvisor_scraper`) emits a raw JSON array
(`data/raw/tripadvisor/tripadvisor_scraper_results.json`, ~7,539 records), and the
load layer (`services/load/mongo`, `uv run dataman-load`) idempotently upserts those
raw records into the MongoDB collection `restaurants_raw_tripadvisor`, keyed on the
natural key `source_url`. What is missing is the **T**: nothing yet cleans, normalizes,
or type-coerces that raw data, and the one existing "transform" service
(`services/transform/tripadvisor_geocode`) is actually **ETL-on-files** — it reads a
JSON file and writes a JSON file, bypassing Mongo entirely. That is paradigm drift: it
does not transform data already loaded into the store, which is the defining property of
ELT.

This feature delivers **one transform service**, `tripadvisor_clean`, operating strictly
**Mongo → Mongo** so the raw collection stays an immutable audit trail and the transform is
re-runnable. **Geocoding is part of producing the cleaned collection** — not a separate
downstream stage. The single output collection `restaurants_clean_tripadvisor` already
contains coordinates.

The transform, for each raw record, performs:

1. **Field cleaning** (pure functions) — decimal-comma rating parsing (`"5,0"`→`5.0`),
   review-count extraction (`"(0 recensioni)"`→`0`), `"NaN"`-sentinel-to-`null` coercion,
   name normalization, address normalization, and best-effort structured extraction of
   `postal_code` / `street` / `city`.
2. **Geocoding enrichment** — geocode the **cleaned** address through Nominatim/OpenStreetMap
   (reusing the existing retry/back-off and 1 req/s discipline) to obtain
   `latitude`/`longitude`. Cleaning the address *before* geocoding is deliberate: it raises
   Nominatim's hit-rate and pin accuracy versus geocoding the raw, `"NaN"`-laden string, and
   enables an optional structured (street + CAP + city + country) query.
3. **Upsert one document** — clean fields **plus** coordinates — into
   `restaurants_clean_tripadvisor`, keyed on `source_url`.

It returns and logs a before/after **quality report** (`CleanReport`, including geocoding
outcomes) that doubles as evidence for the project's stage-5 quality-assessment deliverable.

Because writes are per-record upserts, the (multi-hour) Nominatim portion is **naturally
resumable**: a record that already carries non-null coordinates is skipped on re-run with no
Nominatim call — no separate checkpoint file. A `--skip-geocode` flag also allows a fast
clean-only pass while iterating, preserving the ability to decouple the slow network step
from the fast deterministic cleaning when desired.

The resulting data lineage is:

```
restaurants_raw_tripadvisor
   └─[tripadvisor_clean]──►  restaurants_clean_tripadvisor
                             (clean fields + latitude/longitude)
```

The existing file-based `tripadvisor_geocode` service is **absorbed**: its proven geocoding
core (retry/back-off, `is_nan`, Nominatim discipline) becomes a `geocode.py` module *inside*
`tripadvisor_clean`; its old file→file code path and `tripadvisor-geocode-enrich` console
script are removed.

### Why this matters downstream

- **Entity resolution (pipeline stage 3)** requires `latitude`/`longitude` for proximity
  blocking and requires `rating` as a real number and `total_review` as an integer for
  meaningful comparison and low-review filtering. Raw Tripadvisor data provides none of
  these in usable form.
- **Unified dataset (stage 4)** and the **mandatory queries** (rating difference > 1 star,
  average rating by area) require typed, normalized, deduplicated input.
- **Quality assessment (stage 5)** explicitly requires before/after metrics for duplicate
  removal, name normalization, address standardization, and low-review filtering — the
  `CleanReport` produces exactly these.
- Cleaning **once** at the transform layer prevents every downstream consumer from
  re-implementing (and disagreeing on) the same parsing logic.

## Functional Requirements

### A. New service: `tripadvisor_clean`

- **A1.** A new namespace-package service at `services/transform/tripadvisor_clean`
  importable as `transform.tripadvisor_clean`, following the existing
  `transform.tripadvisor_geocode` module conventions (PEP 420 namespace package,
  `__init__.py`, `__main__.py`, `cli.py`, `config.py`, plus dedicated logic modules
  `cleaners.py` (pure field cleaning), `geocode.py` (geocoding enrichment, absorbed from the
  old `tripadvisor_geocode` service), `transform.py` (orchestration), and a `README.md`).
  This is the **single** Tripadvisor transform service; geocoding is a sub-step inside it,
  not a separate service.
- **A2.** A console entry point `tripadvisor-clean` runnable via `uv run tripadvisor-clean`,
  registered in `pyproject.toml` under `[project.scripts]`.
- **A3.** The service reads documents from the MongoDB collection
  `restaurants_raw_tripadvisor` (the load layer's destination for Tripadvisor) — **not**
  from the raw file on disk.
- **A4.** Cleaning logic lives in a separate module (e.g. `cleaners.py`) as **pure
  functions** that take and return plain Python values, with no MongoDB, network, or I/O
  dependency, so they are independently unit-testable. At minimum:
  - **A4a. Rating parsing** — convert the Italian decimal-comma string rating
    (e.g. `"5,0"`) into a float (`5.0`). Out-of-range or unparseable values become `null`.
  - **A4b. Review-count parsing** — extract the integer review count from strings such as
    `"(0 recensioni)"` / `"(1.234 recensioni)"` into an integer (`0` / `1234`), handling
    Italian thousands separators. Unparseable values become `null`.
  - **A4c. NaN-sentinel coercion** — convert the string sentinel `"NaN"` (case-insensitive,
    trimmed), empty strings, and `None` to a real `null` across **all** fields, reusing the
    existing `is_nan` semantics from `tripadvisor_geocode`.
  - **A4d. Name normalization** — trim and collapse internal whitespace on
    `restaurant_name`; do not destroy meaningful casing (record original if needed for
    audit, but the normalized field is what downstream uses).
  - **A4e. Address normalization + best-effort structured extraction** — trim/collapse
    whitespace and standardize the address string to improve downstream geocoding hit-rate.
    **In addition**, where reliably parseable, extract structured sub-fields as separate
    keys on the clean document: `postal_code` (Italian 5-digit CAP) and `street` (street
    line without the city/postcode tail). Extraction is **best-effort**: when a sub-field
    cannot be confidently parsed it is `null`, and the normalized full `address` string is
    always retained as the source of truth. `city` may also be captured if trivially
    present, but is lower priority. These structured fields let `tripadvisor_geocode`
    optionally issue a structured Nominatim query (more accurate than a free-text query).
  - **A4f. Geocoding enrichment (sub-step, runs on the cleaned address)** — after the
    address is cleaned/normalized, obtain `latitude`/`longitude` via Nominatim/OpenStreetMap.
    Reuse the absorbed core (`geocode_address` retry/progressive back-off, `is_nan`, the
    `>= 1 req/s` Nominatim discipline). Feed it the **cleaned** address (optionally a
    structured street + CAP + city + `country=Italy` query) rather than the raw string.
    A cleaned address that is `null` is **not** sent to Nominatim; its coords are `null`.
- **A5.** The transform writes one document per record into the collection
  `restaurants_clean_tripadvisor` — clean fields **plus** `latitude`/`longitude` — keyed on
  `source_url` mapped to Mongo `_id`, using the same idempotent upsert strategy as the load
  layer (re-running must not create duplicates and must not error on existing keys).
- **A6.** The service returns and logs a `CleanReport` summarizing, at minimum:
  total input records, records written, count of duplicate keys collapsed, count of
  ratings parsed vs. nulled, count of review counts parsed vs. nulled, count of
  `NaN`→`null` coercions, count of names normalized (changed), count of addresses
  normalized (changed), (informational) count of records below a low-review threshold, and
  **geocoding outcomes**: coords found, not found, skipped (null address), and skipped
  (already geocoded on a prior run).
- **A7.** The CLI accepts at least: `--limit N` (process only the first N records, for fast
  smoke testing without the full 7,539), `--skip-geocode` (run the fast clean-only pass,
  leaving coords untouched), `--reset` (clear the destination first), `--delay` / `--timeout`
  (Nominatim knobs, retaining the existing `--delay >= 1.0` guard), and standard logging
  verbosity controls.
- **A8.** Configuration follows the existing `DATAMAN_`-prefixed settings convention
  (`config.py`), exposing: MongoDB connection settings (URI, database, source collection
  `restaurants_raw_tripadvisor`, destination collection `restaurants_clean_tripadvisor`),
  the low-review threshold, and the Nominatim settings (user-agent, timeout, max-retries,
  delay-seconds). It must **not** require the Google API key (mirroring the load layer's
  settings independence).
- **A9. Low-review handling is count-only (no filtering).** The transform **reports** how
  many records fall below `low_review_threshold` but **does not remove** them — every record
  passes through to `restaurants_clean_tripadvisor`. Actual low-review *filtering* is a
  stage-5 (quality assessment) concern on the integrated dataset, deliberately deferred so
  low-review records remain available to entity resolution (stage 3). This is an explicit,
  agreed decision, not an omission.

### B. Absorb `tripadvisor_geocode` as the geocoding sub-step

- **B1.** Preserve the existing, valuable, well-tested logic by **moving** it into
  `tripadvisor_clean/geocode.py`: `geocode_address` (retry / progressive back-off on
  transient Nominatim errors), `is_nan`, the `NAN_VALUE` handling, and the `>= 1 req/s`
  rate-limit discipline.
- **B2.** Geocoding runs **inside** the transform on the cleaned address (A4f) — there is no
  second collection and no second service. The function operates on the in-memory cleaned
  record and attaches `latitude`/`longitude` before the single upsert (A5).
- **B3.** **Resumable / idempotent:** before geocoding a record, check whether
  `restaurants_clean_tripadvisor` already holds that `source_url` with non-null coordinates;
  if so, **skip** the Nominatim call (re-run after interruption resumes, does not restart).
  Implementation may prefetch the set of already-geocoded `_id`s once at start.
- **B4.** A cleaned address that is `null` → coords `null`, counted as a (null-address) skip,
  never sent to Nominatim. An address that geocodes to nothing → `not_found`.
- **B5.** The old file-based path (`geocode_dataset`, `input_path`/`output_path`, JSON
  read/write, atomic `.tmp` rename) is **removed**.
- **B6.** The old `services/transform/tripadvisor_geocode/` package and its
  `tripadvisor-geocode-enrich` console script are **removed** (logic lives in
  `tripadvisor_clean/geocode.py`). Geocoding outcomes are reported through `CleanReport`
  (A6), distinguishing null-address skips from already-geocoded skips.
- **B7.** `--skip-geocode` (A7) lets the transform run clean-only, leaving any existing
  coordinates untouched.

### C. Cross-cutting / packaging

- **C1.** `pyproject.toml` is updated: register the `tripadvisor-clean` script, add the new
  service to the wheel `force-include` list, and rely on the existing `transform` entry in
  ruff `known-first-party`. **Remove** the old `tripadvisor-geocode-enrich` script and the
  `tripadvisor_geocode` wheel `force-include` entry.
- **C2.** The transform reuses a MongoDB connection approach consistent with
  `services/load/mongo` (same driver, lazy client + explicit `ping`, same connection-settings
  style) rather than inventing a new one.
- **C3.** All new/changed code passes the project's pre-commit gates
  (`ruff --fix` + `ruff-format`) and targets `py311`.
- **C4.** Documentation is updated: the root `CLAUDE.md` tooling block and the relevant
  `docs/` files (e.g. `etl-design.md`, `PIPELINE.md`) reflect that the Tripadvisor T-layer
  exists as a single Mongo→Mongo transform (cleaning + geocoding) producing
  `restaurants_clean_tripadvisor`, and that `tripadvisor-geocode-enrich` is gone.

## Possible Edge Cases

- **Decimal-comma vs. decimal-point ratings** — `"5,0"` vs. an unexpected `"5.0"`; both
  should parse. A rating like `"4,5 di 5"` or stray suffixes should be tolerated or nulled,
  never crash.
- **Review-count formats** — `"(0 recensioni)"`, `"(1 recensione)"` (singular),
  `"(1.234 recensioni)"` (Italian thousands separator), `"NaN"`, missing field — all must
  resolve to an integer or `null` without error.
- **Pervasive `"NaN"` strings** — present across many fields (`cuisine_type`, `email`,
  `price_range`, `review`, `website`, `working_days_hours`, etc.); coercion must be applied
  uniformly, including to the key/identity fields' *values* (never to the `_id`/key itself
  in a way that drops the record).
- **Duplicate `source_url`** — two raw records sharing the same `source_url`; upsert must
  collapse to one cleaned doc deterministically and the report must count the collapse.
- **Missing `source_url`** — a raw record lacking the natural key cannot be keyed; it must
  be skipped and reported, not crash the run.
- **Empty / whitespace-only `restaurant_name` or `address`** after trimming → treated as
  `null`.
- **Address that geocodes to nothing** vs. **address that is `null`** — distinct outcomes
  (`not_found` with non-null address vs. `skipped` with null address).
- **Geocode re-run after partial completion** — already-coordinated records must be skipped;
  the run must not re-pay the Nominatim cost or double-write.
- **Empty source collection / missing collection** — clear, non-crashing message and an
  all-zero report.
- **Mongo unreachable** — clear, actionable error (consistent with the load layer), not a
  raw stack trace.
- **`--limit` larger than available records** — process all available, no error.
- **Re-running `tripadvisor_clean` after the raw collection grew** — new records added,
  existing ones updated in place, no duplicates (idempotency).
- **Nominatim transient failures / timeouts** — existing retry/back-off applies; a record
  that exhausts retries is recorded as `not_found`, not fatal to the whole run.

## Acceptance Criteria

- **AC1.** `uv run tripadvisor-clean` reads `restaurants_raw_tripadvisor` and populates the
  single collection `restaurants_clean_tripadvisor` with type-coerced, normalized documents
  keyed on `source_url`.
- **AC2.** In the cleaned collection: `rating` is a float (or `null`), `total_review` is an
  integer (or `null`), and no field contains the string `"NaN"` — all such sentinels are
  real `null`.
- **AC3.** Each cleaned document includes `latitude`/`longitude` (real numbers when the
  cleaned address geocoded, `null` otherwise) — coordinates live in the same collection, not
  a separate one.
- **AC4.** Running `tripadvisor-clean` twice yields the same document count and content
  (idempotent; no duplicates).
- **AC5.** Interrupting the run and re-running does **not** re-geocode records that already
  have non-null coordinates (verifiable: the second run reports those as already-done and
  issues no Nominatim calls for them).
- **AC6.** `--skip-geocode` performs a clean-only pass: fields are cleaned/updated but no
  Nominatim calls are made and existing coordinates are left untouched.
- **AC7.** `tripadvisor-clean` prints/logs a `CleanReport` containing before/after counts
  for: duplicates collapsed, ratings parsed/nulled, review counts parsed/nulled,
  NaN→null coercions, names normalized, addresses normalized, low-review records, and
  geocoding outcomes (found / not_found / null-address skip / already-done skip).
- **AC8.** The old `services/transform/tripadvisor_geocode/` package and the
  `tripadvisor-geocode-enrich` script are removed; no JSON-file geocoding code path remains.
- **AC9.** The pure cleaning functions are unit-tested with no Mongo/network dependency; the
  Mongo path (with Nominatim mocked) is exercised via `mongomock`, including idempotency and
  geocoding resumability. `uv run pytest` passes; `uv run pre-commit run --all-files` is clean.
- **AC10.** `pyproject.toml` registers `tripadvisor-clean`, includes the new package in the
  wheel `force-include`, and removes the `tripadvisor-geocode-enrich` script and the old
  package's wheel entry; `CLAUDE.md` and the relevant `docs/` reflect the single combined
  transform and paradigm.

## Resolved Decisions

- **Raw value preservation — RESOLVED:** rely on `restaurants_raw_tripadvisor` as the
  audit trail; keep clean docs lean (no `rating_raw`/`*_raw` shadow fields). *(agreed)*
- **Address normalization scope — RESOLVED:** do whitespace/separator standardization
  **plus** best-effort structured extraction of `postal_code` and `street` (and `city`
  where trivial) as separate fields; always retain the normalized full `address`. See A4e.
  *(agreed)*
- **Low-review threshold — RESOLVED:** configurable `low_review_threshold`, default `10`
  (i.e. fewer than 10 reviews flagged in the report). Not hard-coded. *(agreed)*
- **Record key + `ta_location_id` — RESOLVED:** `_id` stays the natural key `source_url`
  (no new IDs minted; idempotency + raw↔clean join preserved). Additionally, the cleaner
  extracts TripAdvisor's stable location id from the URL (`-d<n>-`) into a regular field
  `ta_location_id` — verified unique 7,539/7,539 — as a clean join/blocking key for entity
  resolution. *(agreed)*
- **Geocoding placement — RESOLVED:** geocoding is **part of** the transform, not a separate
  stage. One service (`tripadvisor_clean`), one output collection
  (`restaurants_clean_tripadvisor`) that already contains coordinates. The old
  `tripadvisor_geocode` service is absorbed. *(agreed)*
- **Address used for geocoding — RESOLVED:** geocode the **cleaned** address (clean-first)
  for better hit-rate/accuracy; optionally a structured street + CAP + city + country query.
  *(agreed — chosen for quality)*
- **Build order — RESOLVED:** build the geocoding module (`geocode.py`) first so it
  establishes the Mongo/Nominatim pattern, then the field cleaners, then the orchestrator.
  (Runtime order within the transform is still: clean address → geocode → finish.) *(agreed)*

## Open Questions

- *(none outstanding)* — structured-extraction depth (`street`/`postal_code`/`city`) is
  best-effort; revisit only if geocoding accuracy proves insufficient.

## Out of Scope

- Cleaning/transforming the **Google Places** and **TheFork** sources — this feature only
  establishes the pattern on Tripadvisor; the other two are follow-up specs that copy it.
- **Entity resolution** (pipeline stage 3) — record linkage between platforms and the seed.
- **Unified dataset** construction (stage 4) and the **ClickHouse** integrated ratings
  table / mandatory analytical queries.
- The full **quality-assessment report** deliverable (stage 5) — this feature provides the
  `CleanReport` metrics that *feed* it, but not the consolidated assessment.
- Changing the **scrapers / extract layer** or the **load layer** behavior.
- Switching the geocoding provider away from Nominatim/OpenStreetMap, or adding paid
  geocoding.
- Re-geocoding Google Places coordinates (the seed coordinates remain authoritative and are
  never recomputed, per project architecture).
- Mongo authentication / deployment hardening (local dev runs without auth by design).

## Feature Testing Guidelines

Create test file(s) under `tests/transform/` (consistent with `pythonpath = ["services"]`
and the project's `mongomock` dev dependency). Cover the following without going too heavy:

- **Pure cleaners (no Mongo, no network):**
  - `parse_rating`: `"5,0"`→`5.0`, `"4,5"`→`4.5`, `"NaN"`→`null`, garbage→`null`, already
    a number→that number.
  - `parse_review_count`: `"(0 recensioni)"`→`0`, `"(1 recensione)"`→`1`,
    `"(1.234 recensioni)"`→`1234`, `"NaN"`/missing→`null`.
  - `nan_to_none` / `is_nan`: `"NaN"`, `"nan"`, `" NaN "`, `""`, `None`→`null`; real values
    pass through unchanged.
  - `normalize_name` / `normalize_address`: collapse whitespace, trim; whitespace-only→`null`.
  - `extract_address_parts`: pull `postal_code` (5-digit CAP) and `street` from a typical
    Milan address; return `null` parts when not confidently parseable.
- **`geocode.py` core (no Mongo; Nominatim mocked/stubbed):**
  - `geocode_address`: success → `(lat, lon)`; transient `GeocoderTimedOut` then success →
    retried; exhausted retries → `(NaN, NaN)` / not-found, never raises.
- **`tripadvisor_clean` Mongo path (mongomock, Nominatim mocked):**
  - Happy path: a small seeded `restaurants_raw_tripadvisor` produces correctly typed,
    normalized docs **with `latitude`/`longitude`** in `restaurants_clean_tripadvisor`.
  - Idempotency: running twice yields the same count and content (no duplicates).
  - Duplicate `source_url` collapses to one doc and is counted in the report.
  - Missing `source_url` record is skipped and reported, not fatal.
  - **Geocoding resumability:** a record already present with non-null coords is skipped on
    re-run and triggers no geocoder call (assert the stub is not invoked for it).
  - **Null-address** record is written with null coords, counted as a null-address skip,
    never sent to the geocoder.
  - **`--skip-geocode`:** fields are cleaned but the geocoder stub is never called and
    existing coords are untouched.
  - `CleanReport` fields (incl. geocoding outcomes) reflect the seeded fixture's expected
    counts.
- **Config wiring:** the service builds its settings from `DATAMAN_`-prefixed env without
  requiring the Google API key.
