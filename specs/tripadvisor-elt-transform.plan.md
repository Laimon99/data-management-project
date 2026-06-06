# Implementation Plan — Tripadvisor ELT Transform Pipeline

**Spec:** [`tripadvisor-elt-transform.md`](./tripadvisor-elt-transform.md)
**Branch:** `feature/tripadvisor-elt-transform`
**Target:** Python 3.11, `uv`, MongoDB, `mongomock` for tests.

This plan turns the spec into a concrete, ordered build. Verification is via `uv run pytest`
(reads source directly through `pythonpath = ["services"]`) rather than the console script,
because of the **editable-install snapshot gotcha** (`CLAUDE.md`): `uv run <script>` keeps
running the old copied snapshot until `uv sync --reinstall-package data-management-project`.
We drive everything from tests and only smoke-test the entry point at the end (post-reinstall).

---

## 0. Architectural decisions (locked)

1. **One transform service, one output collection.** `tripadvisor_clean` reads
   `restaurants_raw_tripadvisor` and writes `restaurants_clean_tripadvisor`. **Geocoding is
   a sub-step of this transform**, not a separate stage — the cleaned docs already contain
   `latitude`/`longitude`. There is no `restaurants_geocoded_tripadvisor`.
2. **Mongo → Mongo only.** Raw collection is never mutated (immutable audit trail). This is
   the defining property of ELT.
3. **Absorb the old geocode service.** The proven core of
   `services/transform/tripadvisor_geocode` (`geocode_address` retry/back-off, `is_nan`,
   Nominatim `>= 1 req/s` discipline) **moves** into `tripadvisor_clean/geocode.py`. The old
   package, its file→file path, and the `tripadvisor-geocode-enrich` script are **removed**.
4. **Clean-first, then geocode (quality).** Within the transform the order is: clean fields
   (incl. address normalization + structured extraction) → geocode the **cleaned** address →
   upsert one doc. Geocoding cleaned/structured addresses beats geocoding raw `"NaN"`-laden
   strings.
5. **Natural key throughout: `source_url` → Mongo `_id`** (identical to the load layer).
6. **Reuse the load layer's persistence idioms** (`open_collection` lazy client + `ping`,
   `serial_upsert`/`bulk_upsert` dual write paths because mongomock can't run `bulk_write`,
   `BATCH_SIZE = 1000`, `_prepare`-style skip-on-missing-key, metadata stamping).
7. **Resumable geocoding.** Skip records that already hold non-null coords (prefetch the set
   of done `_id`s once). A `--skip-geocode` flag gives a fast clean-only pass.
8. **Cleaning logic = pure functions** in `cleaners.py` (no Mongo/network/IO), unit-testable
   in isolation and reusable by the other two sources later.

### Build order (per user direction "geocode is the first step")
Build **`geocode.py` first** — it establishes the Mongo-aware enrichment + Nominatim pattern.
Then `cleaners.py`, then `transform.py` orchestration, then `cli.py`. (Runtime order inside
the transform remains clean→geocode; build order is geocode-module-first.)

---

## Phase 1 — Scaffold the single service + packaging

`services/transform/tripadvisor_clean/`:
- `__init__.py` — package docstring + public exports (mirror `tripadvisor_geocode/__init__.py`).
- `__main__.py` — `from .cli import app; app()`.
- `config.py` — settings (Phase 3).
- `geocode.py` — geocoding core, absorbed (Phase 2).
- `cleaners.py` — pure field cleaning (Phase 4).
- `transform.py` — orchestration + `CleanReport` + Mongo I/O (Phase 5).
- `cli.py` — Typer app (Phase 6).
- `README.md` — source-of-truth doc (Phase 8).

`pyproject.toml`:
- `[project.scripts]`: **add** `tripadvisor-clean = "transform.tripadvisor_clean.cli:app"`;
  **remove** `tripadvisor-geocode-enrich = "transform.tripadvisor_geocode.cli:app"`.
- `[tool.hatch.build.targets.wheel.force-include]`: **add**
  `"services/transform/tripadvisor_clean" = "transform/tripadvisor_clean"`; **remove** the
  `tripadvisor_geocode` entry.
- `known-first-party` already includes `transform` (no change).

**Done when:** `python -c "import transform.tripadvisor_clean"` works.

---

## Phase 2 — `geocode.py` (absorb + adapt; built first)

Move from `tripadvisor_geocode/geocode.py`, keep the algorithm, drop file I/O.

- **Keep verbatim:** `is_nan`, `NAN_VALUE`, `geocode_address(geocoder, address, *, timeout,
  max_retries, delay_seconds)` (retry/progressive back-off; returns `(lat, lon)` strings or
  `(NaN, NaN)`).
- **Add** a thin `build_query(cleaned_record)` helper: prefer a structured Nominatim query
  `{"street": street, "postalcode": postal_code, "city": city or "Milano",
  "country": "Italy"}` when structured parts exist, else fall back to the cleaned free-text
  address. (Optional but cheap; improves accuracy.)
- **Drop:** `geocode_dataset`, `reorder_with_coords` file logic, all JSON read/write +
  atomic `.tmp` rename.
- Expose a small `geocode_one(geocoder, cleaned_record, settings) -> (lat, lon)` that the
  orchestrator calls per record (handles null-address → `(None, None)` without a network call).

**Done when:** `tests/transform/test_geocode_core.py` passes (Nominatim mocked): success,
timeout-then-success retry, exhausted-retries→not-found, null-address→no call.

---

## Phase 3 — `config.py`

`pydantic_settings.BaseSettings`, `env_prefix="DATAMAN_"`, no required fields (no Google key):
```text
mongo_uri:               str = "mongodb://localhost:27017"
mongo_db:                str = "dataman"
source_collection:       str = "restaurants_raw_tripadvisor"
destination_collection:  str = "restaurants_clean_tripadvisor"
low_review_threshold:    int = 10
batch_size:              int = 1000
# Nominatim (carried over from the old geocode config)
delay_seconds:           float = 1.2   # >= 1s per Nominatim ToS
timeout:                 int = 10
max_retries:             int = 2
user_agent:              str = "dataman_restaurant_geocoder_milan/1.0 (transform)"
```

**Done when:** `CleanSettings()` instantiates from env without a Google key.

---

## Phase 4 — `cleaners.py` (pure functions)

No Mongo, no network. Functions:
- `is_nan` / `nan_to_none` — reuse the geocode semantics (single definition; import from
  `geocode.py` to avoid duplication).
- `parse_rating("5,0") -> 5.0` — comma→dot, defensively accept `"5.0"`, reject out of
  `[0,5]`, `is_nan`/garbage → `None`.
- `parse_review_count("(1.234 recensioni)") -> 1234` — regex digit token, drop Italian
  thousands `.`, `int()`; `"(1 recensione)"`→`1`; `is_nan`/no digits → `None`.
- `normalize_name` / `normalize_address` — trim + collapse whitespace (`re.sub(r"\s+"," ")`);
  empty → `None`. Preserve casing.
- `extract_address_parts(addr) -> {"postal_code","street","city"}` — best-effort: CAP regex
  `\b\d{5}\b`; `street` = line before the CAP/city tail; `city` only if trivial. Conservative
  regexes — a wrong structured field is worse than a null one. Full `address` always retained.
- `clean_record(raw) -> dict` — apply all field cleaners + `nan_to_none` across remaining
  fields; merge structured address parts. Does **not** touch `_id`/keying or geocoding.

**Done when:** `tests/transform/test_clean_cleaners.py` passes (table-driven, per spec).

---

## Phase 5 — `transform.py` (orchestration + Mongo I/O)

Port the shape of `load/mongo/loader.py`.

- **`CleanReport`** dataclass: `read, written, duplicates_collapsed, missing_key,
  ratings_parsed, ratings_nulled, reviews_parsed, reviews_nulled, nan_coerced,
  names_normalized, addresses_normalized, low_review,
  geocode_found, geocode_not_found, geocode_skipped_null_addr, geocode_skipped_done`.
- **`_prepare(raw) -> dict | None`** — pull `source_url`; skip (None) if missing/blank;
  `_id = source_url`; run `clean_record`; stamp `_transformed_at` (UTC), `_source_collection`;
  update counters by comparing pre/post values.
- **`clean_collection(source, dest, settings, *, reset=False, skip_geocode=False, limit=None,
  geocoder=None, writer=serial_upsert|bulk_upsert) -> CleanReport`**:
  1. If `reset`: `dest.delete_many({})`.
  2. If not `skip_geocode`: prefetch `done = {_id for doc in dest.find({lat: {$ne: null}})}`
     for resumability.
  3. Iterate `source.find()` (respect `limit`); `_prepare` each; track seen `_id`s to count
     `duplicates_collapsed`.
  4. Geocoding per record (unless `skip_geocode` or `_id in done` or null cleaned address):
     call `geocode.geocode_one`; set `latitude`/`longitude`; bump the matching geocode
     counter. Respect `time.sleep(delay_seconds)` exactly as today (only on real calls).
  5. Batch + flush via `writer` (default `bulk_upsert`; tests inject `serial_upsert`).
- **`open_transform_collections(settings) -> (client, source, dest)`** — lazy `MongoClient`
  + `ping`; import `MongoClient` inside the function for monkeypatchability.
- **Capture decision** as a header comment in `transform.py` (brainstorming Capture step).

**Done when:** `tests/transform/test_clean_transform.py` (mongomock + mocked geocoder) passes:
happy path (typed+normalized+coords), idempotency, duplicate/missing-key handling,
geocoding resumability (done record → geocoder not called), null-address skip,
`--skip-geocode` behavior, and `CleanReport` assertions.

---

## Phase 6 — `cli.py` (Typer)

Mirror the old geocode CLI:
- `_configure_logging()`.
- One command, options: `--limit/-n`, `--skip-geocode`, `--reset`, `--delay` (keep the
  `>= 1.0` guard), `--timeout`, verbosity.
- Build `CleanSettings()`, `open_transform_collections`, build a `Nominatim` geocoder,
  call `clean_collection`, print `json.dumps(asdict(report), indent=2)`.
- Catch `PyMongoError` → friendly message + `raise typer.Exit(1)` (parity with load CLI).

**Done when:** post-reinstall, `uv run tripadvisor-clean --limit 5 --skip-geocode` runs against
live Mongo (manual smoke).

---

## Phase 7 — Remove the old `tripadvisor_geocode` service

- Delete `services/transform/tripadvisor_geocode/` (logic now lives in `tripadvisor_clean`).
- Remove/replace its tests.
- Confirm `pyproject.toml` no longer references it (script + wheel entry removed in Phase 1).
- Grep the repo for `tripadvisor-geocode-enrich` / `tripadvisor_geocode` and fix stragglers.

**Done when:** no references remain; `uv run pytest` still green.

---

## Phase 8 — Docs & wiring

- **`tripadvisor_clean/README.md`** — purpose, lineage (raw → clean+coords), config env,
  run command, `--skip-geocode`, resumability/idempotency contract, `CleanReport` fields.
- **`CLAUDE.md`** tooling block — replace `tripadvisor-geocode-enrich` with
  `uv run tripadvisor-clean`; update the project-status paragraph (Tripadvisor T-layer =
  single Mongo→Mongo transform that cleans + geocodes).
- **`docs/etl-design.md` / `docs/PIPELINE.md`** — record the single combined transform, the
  one output collection, and that this is the template for the other two sources.

---

## Phase 9 — Full verification

1. `uv run pytest` — all green (pure cleaners + geocode core + Mongo path via mongomock).
2. `uv run pre-commit run --all-files` — ruff lint + format clean, `py311`.
3. `uv sync --reinstall-package data-management-project`.
4. Smoke vs. live Mongo (`docker compose up -d mongo`):
   - `uv run dataman-load tripadvisor` (ensure raw present).
   - `uv run tripadvisor-clean --limit 20` → inspect `restaurants_clean_tripadvisor`:
     `rating` float, `total_review` int, no `"NaN"`, `latitude`/`longitude` present.
   - Re-run → confirm already-geocoded records skipped (report `geocode_skipped_done`).
   - `--skip-geocode` run → no Nominatim calls, coords untouched.
5. Map each spec **AC1–AC10** to a passing test or smoke observation before the PR.

---

## File-change summary

**New:**
- `services/transform/tripadvisor_clean/{__init__,__main__,config,geocode,cleaners,transform,cli}.py`
- `services/transform/tripadvisor_clean/README.md`
- `tests/transform/{test_geocode_core,test_clean_cleaners,test_clean_transform}.py`

**Modified:**
- `pyproject.toml` (add clean script + wheel; remove geocode script + wheel)
- `CLAUDE.md`, `docs/etl-design.md`, `docs/PIPELINE.md`

**Removed:**
- `services/transform/tripadvisor_geocode/` (entire package)
- old geocode test(s)

**Untouched (explicitly):** scrapers, load layer, Google/TheFork sources, ClickHouse,
entity resolution, Google seed coordinates.

---

## Risks & mitigations

- **Snapshot gotcha** → verify via `pytest`; reinstall before any console-script smoke test.
- **mongomock can't `bulk_write`** → dual-writer pattern (`serial_upsert` in tests).
- **Coupling clean + slow geocoding** → resumability + `--skip-geocode` keep the fast path
  fast and avoid re-paying Nominatim cost.
- **Structured address extraction wrong** → keep regexes conservative, null on doubt, always
  retain full `address`; geocode falls back to free-text.
- **Nominatim ToS** → preserve `>= 1s` delay + CLI guard; resumability reduces calls.
- **Losing proven geocode behavior during the move** → port `geocode_address` verbatim and
  cover it with `test_geocode_core.py` before wiring it into the orchestrator.
```
