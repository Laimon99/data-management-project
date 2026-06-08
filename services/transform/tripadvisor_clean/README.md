# transform.tripadvisor_clean

The **single Tripadvisor transform** — the `T` of the ELT pipeline for Tripadvisor.
Operates **Mongo → Mongo**: the raw collection is never mutated (immutable audit trail).

```
restaurants_raw_tripadvisor
   └─[tripadvisor-clean]──►  restaurants_clean_tripadvisor   (typed + structured + geocoded + flagged)
```

It is at **parity** with `google_clean` and `thefork_clean`: rich-field parsing,
per-record quality flags, full-run stale-delete convergence, and a source/destination
collision guard. See [`clean-dataset-schema.md`](clean-dataset-schema.md) for the full
output schema, [`drop-policy.md`](drop-policy.md) for the flag-first stance, and
[`../../extract/tripadvisor_scraper/eda-report.md`](../../extract/tripadvisor_scraper/eda-report.md)
for the data-quality analysis that motivates each step.

## What it does

For each raw record (pure functions in `cleaners.py`):

1. **Type-repair** — `rating` `"5,0"` → float `5.0` (range `[0,5]`), `total_review`
   `"(1.234 recensioni)"` → int `1234`, `"NaN"`/empty → real `null` across all fields.
2. **Normalize** — `restaurant_name` / `address` whitespace + separators; contacts
   (`website`/`phone`/`email`) `"NaN"`/blank → `null`, with `phone` and `website`
   canonicalized for direct ER comparison.
3. **Structure the 1NF-violation fields** —
   - `number_photo_uploaded` → `photo_count` (int);
   - `price_range` → `price_band` + ordinal `price_tier_level` (€→1, €€-€€€→2, €€€€→4);
   - `cuisine_type` CSV → `cuisines: list[str]` (trimmed, case-insensitive de-dupe);
   - `working_days_hours` flattened Italian string → `opening_hours: [{day, opens, closes}]`
     (**automatic conservative parser**, English day names, split shifts preserved,
     `Chiuso` days omitted, `closes_next_day` for past-midnight; 100% of present values
     parse);
   - `review` → slim, capped `reviews` `{nickname, contributions, title, text, date}`
     (`"Scopri di più"` read-more suffix stripped, Italian date → ISO) + `sample_size`.
   - The replaced raw fields are **dropped** from the clean document.
4. **Lift `ta_location_id`** (the `-d<n>-` URL token) as a stable join/blocking key; `_id`
   stays `source_url`. Best-effort structured address parts (`street`/`house_number`/
   `postal_code`/`city`).
5. **Geocode the cleaned address** (`geocode.py`, Nominatim/OpenStreetMap) into
   `latitude`/`longitude` — clean-first for higher hit-rate; structured query when address
   parts were extracted, else the free-text address. Geocoding is a **sub-step**, not a
   separate stage.
6. **Derive quality flags** — `has_*` booleans + a `flags` reason list (see below).
7. **Upsert one document** keyed on `source_url` → `_id` (idempotent).

## Quality flags

Each record carries `has_rating`, `has_review_count`, `low_review`, `has_address`,
`has_coordinates`, `has_reviews`, `has_hours`, `has_phone`, `has_website`, `has_email`,
and a `flags: list[str]` drawn from: `no_rating`, `missing_review_count`, `low_review`,
`missing_address`, `geocode_not_found`, `missing_coordinates`, `rating_with_zero_reviews`,
`no_reviews`, `no_hours`. Flags are **count-only signals, never drop rules** — see
[`drop-policy.md`](drop-policy.md).

## Run

```bash
docker compose up -d mongo          # destination + source live here
uv run dataman-load tripadvisor     # ensure restaurants_raw_tripadvisor is populated
uv run tripadvisor-clean            # clean + structure + geocode + flag the full dataset
uv run tripadvisor-clean --limit 20 # quick slice
uv run tripadvisor-clean --skip-geocode   # fast clean-only pass (no Nominatim calls)
uv run tripadvisor-clean --reset    # empty the destination first (destructive)
```

> **Editable-install gotcha** (see root `CLAUDE.md`): `uv run tripadvisor-clean` runs a
> copied snapshot. After editing service code, run
> `uv sync --reinstall-package data-management-project` before smoke-testing the script.
> For verification prefer `uv run pytest` (reads source directly).

## Rerun convergence & safety

- **Idempotent upsert** keyed on `source_url` → re-runs do not duplicate.
- **Full-run stale-delete**: on a full run (`limit is None`), destination docs whose
  `source_url` vanished from the source are deleted (`stale_deleted`). A `--limit` run is
  intentionally partial and **never** sync-deletes.
- **Collision guard**: if `source_collection == destination_collection`, the transform
  raises `ValueError` before reading or writing (refuses to mutate the raw collection).
- **Geocoding is resumable**: records that already hold both coordinates are skipped (no
  Nominatim call); partial coordinates are re-geocoded; `--skip-geocode` updates the
  deterministic clean fields while preserving existing coordinates.

## Configuration

`DATAMAN_`-prefixed env (`config.py`); no Google API key required:

| setting | default |
|---|---|
| `DATAMAN_MONGO_URI` | `mongodb://localhost:27017` |
| `DATAMAN_MONGO_DB` | `dataman` |
| `DATAMAN_SOURCE_COLLECTION` | `restaurants_raw_tripadvisor` |
| `DATAMAN_DESTINATION_COLLECTION` | `restaurants_clean_tripadvisor` |
| `DATAMAN_LOW_REVIEW_THRESHOLD` | `10` |
| `DATAMAN_REVIEW_CAP` | `20` (max nested reviews kept per record) |
| `DATAMAN_DELAY_SECONDS` | `1.2` (≥ 1s per Nominatim ToS) |
| `DATAMAN_TIMEOUT` | `10` |
| `DATAMAN_MAX_RETRIES` | `2` |

## CleanReport

Returned and printed as JSON; feeds the stage-5 quality assessment. Counters:

- **Volume/convergence**: `read`, `written`, `duplicates_collapsed`, `missing_key`,
  `stale_deleted`.
- **Type repair**: `ratings_parsed`/`ratings_nulled`, `reviews_parsed`/`reviews_nulled`,
  `nan_coerced`, `names_normalized`, `addresses_normalized`.
- **Rich-field coverage**: `photo_count_parsed`, `price_parsed`, `cuisines_present`,
  `multi_cuisine`, `opening_hours_parsed`, `with_reviews`, `with_phone`, `with_website`,
  `with_email`.
- **Quality flags**: `with_rating`/`without_rating`, `missing_review_count`, `low_review`
  (count only — records are **not** removed), `rating_with_zero_reviews`.
- **Geocoding**: `geocode_found`/`geocode_not_found`/`geocode_skipped_null_addr`/
  `geocode_skipped_done`.
