# transform.tripadvisor_clean

The **single Tripadvisor transform** — the `T` of the ELT pipeline for Tripadvisor.
Operates **Mongo → Mongo**: the raw collection is never mutated (immutable audit trail).

```
restaurants_raw_tripadvisor
   └─[tripadvisor-clean]──►  restaurants_clean_tripadvisor   (clean fields + latitude/longitude)
```

## What it does

For each raw record it:

1. **Cleans fields** (pure functions in `cleaners.py`):
   - `rating`: Italian decimal-comma `"5,0"` → float `5.0` (out-of-range / garbage → `null`)
   - `total_review`: `"(1.234 recensioni)"` → int `1234` (Italian thousands separator)
   - `"NaN"` sentinel / empty / whitespace → real `null`, across all fields
   - `restaurant_name`, `address`: trim + collapse whitespace, normalize separators
   - best-effort structured extraction: `postal_code` (CAP), `street`, `city`
   - `ta_location_id`: TripAdvisor's stable location id from the URL (`-d28119476-` →
     `"28119476"`) — a clean join/blocking key for entity resolution (`_id` stays `source_url`)
2. **Geocodes the cleaned address** (`geocode.py`, Nominatim/OpenStreetMap) into
   `latitude`/`longitude`. Clean-first → higher hit-rate; a structured (street + CAP +
   city + country) query is used when parts were extracted, else the free-text address.
3. **Upserts one document** (clean fields + coords) into `restaurants_clean_tripadvisor`,
   keyed on `source_url` → `_id` (idempotent; re-running converges, no duplicates).

Geocoding is a **sub-step of the transform**, not a separate stage — there is no separate
geocoded collection.

## Field-by-field

The natural key stays `source_url` (→ Mongo `_id`); **no new IDs are minted**. Every field
also passes through `NaN`/empty → `null` coercion. The 13 raw fields become 13 cleaned +
`ta_location_id` + 3 structured (`postal_code`/`street`/`city`) + 2 coordinates + 3 metadata.

| Raw field | Raw example | Transform | Output field | Output type |
|---|---|---|---|---|
| `source_url` | `https://…-d28119476-Reviews-Dop20-…html` | natural key → also set as `_id` | `source_url` (+ `_id`) | `str` |
| *(from `source_url`)* | `-d28119476-` | extract TripAdvisor location id | `ta_location_id` | `str \| null` |
| `restaurant_name` | `"  Dop20 "` | trim + collapse whitespace | `restaurant_name` | `str \| null` |
| `rating` | `"5,0"` | Italian comma → float, range `[0,5]` | `rating` | `float \| null` |
| `total_review` | `"(0 recensioni)"` | extract int, drop thousands `.` | `total_review` | `int \| null` |
| `address` | `"Via Vela, 14, 20133 Milano Italia"` | normalize whitespace/commas | `address` | `str \| null` |
| `cuisine_type` | `"NaN"` | `NaN` → `null`, else passthrough | `cuisine_type` | `str \| null` |
| `price_range` | `"NaN"` | `NaN` → `null` | `price_range` | `str \| null` |
| `number_photo_uploaded` | `"NaN"` | `NaN` → `null` | `number_photo_uploaded` | `str \| null` |
| `website` | `"NaN"` | `NaN` → `null` | `website` | `str \| null` |
| `phone_number` | `"+39 320 …"` | `NaN` → `null`, else passthrough | `phone_number` | `str \| null` |
| `email` | `"NaN"` | `NaN` → `null` | `email` | `str \| null` |
| `working_days_hours` | `"NaN"` | `NaN` → `null` | `working_days_hours` | `str \| null` |
| `review` | `"NaN"` | `NaN` → `null` | `review` | `str \| null` |
| *(derived)* | — | parsed from cleaned `address` | `postal_code` | `str \| null` |
| *(derived)* | — | parsed from cleaned `address` | `street` | `str \| null` |
| *(derived)* | — | parsed from cleaned `address` | `city` | `str \| null` |
| *(derived)* | — | geocode cleaned address (Nominatim) | `latitude` | `float \| null` |
| *(derived)* | — | geocode cleaned address (Nominatim) | `longitude` | `float \| null` |
| *(metadata)* | — | set to `source_url` | `_id` | `str` |
| *(metadata)* | — | `datetime.now(UTC)` | `_transformed_at` | `datetime` |
| *(metadata)* | — | source collection name | `_source_collection` | `str` |

## Run

```bash
docker compose up -d mongo          # destination + source live here
uv run dataman-load tripadvisor     # ensure restaurants_raw_tripadvisor is populated
uv run tripadvisor-clean            # clean + geocode the full dataset
uv run tripadvisor-clean --limit 20 # quick slice
uv run tripadvisor-clean --skip-geocode   # fast clean-only pass (no Nominatim calls)
uv run tripadvisor-clean --reset    # empty the destination first (destructive)
```

> **Editable-install gotcha** (see root `AGENTS.md`): `uv run tripadvisor-clean` runs a
> copied snapshot. After editing service code, run
> `uv sync --reinstall-package data-management-project` before smoke-testing the script.
> For verification prefer `uv run pytest` (reads source directly).

## Resumability & idempotency

- Per-record upsert keyed on `source_url` → re-runs do not duplicate.
- Geocoding is **resumable**: records that already hold non-null coordinates are skipped
  (no Nominatim call), so an interrupted run resumes instead of restarting.
- `--skip-geocode` cleans/updates fields but makes no Nominatim calls and leaves existing
  coordinates untouched.

## Configuration

`DATAMAN_`-prefixed env (`config.py`); no Google API key required:

| setting | default |
|---|---|
| `DATAMAN_MONGO_URI` | `mongodb://localhost:27017` |
| `DATAMAN_MONGO_DB` | `dataman` |
| `DATAMAN_SOURCE_COLLECTION` | `restaurants_raw_tripadvisor` |
| `DATAMAN_DESTINATION_COLLECTION` | `restaurants_clean_tripadvisor` |
| `DATAMAN_LOW_REVIEW_THRESHOLD` | `10` |
| `DATAMAN_DELAY_SECONDS` | `1.2` (≥ 1s per Nominatim ToS) |
| `DATAMAN_TIMEOUT` | `10` |
| `DATAMAN_MAX_RETRIES` | `2` |

## CleanReport

Returned and printed as JSON; feeds the Step-5 quality assessment. Fields: `read`,
`written`, `duplicates_collapsed`, `missing_key`, `ratings_parsed`/`ratings_nulled`,
`reviews_parsed`/`reviews_nulled`, `nan_coerced`, `names_normalized`,
`addresses_normalized`, `low_review` (count only — records are **not** removed),
`geocode_found`/`geocode_not_found`/`geocode_skipped_null_addr`/`geocode_skipped_done`.
