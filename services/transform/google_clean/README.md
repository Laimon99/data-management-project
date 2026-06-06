# transform.google_clean

The **single Google Places transform** — the `T` of the ELT pipeline for Google.
Operates **Mongo → Mongo**: the raw collection is never mutated (immutable audit trail).

```
restaurants_raw_google
   └─[google-clean]──►  restaurants_clean_google   (lean projection + flags + features)
```

## Output schema

Full field-by-field reference (types + live coverage %): **[`clean-dataset-schema.md`](clean-dataset-schema.md)**.
The clean doc is keyed on `place_id` (→ `_id`) and **drops the heavy raw `details` blob**.
Beyond the passthrough/normalized core (`name`, `latitude`/`longitude`, `address`,
`rating`, `review_count`, `types`), the **new/derived** fields are:

- **Structured address** (from `details.addressComponents`): `street`, `street_number`,
  `postal_code`, `locality`, `province`, `country`, canonical `city`, `city_out_of_area`.
- **Classification:** `category_tier`, `is_dining`.
- **Quality flags:** `has_rating`, `low_review`, `is_operational`, `name_is_geographic`,
  `flags[]` (reason list).
- **Features:** `photo_count`, `price_range` (`{start,end,currency}`), `has_website`,
  `has_phone`, `website`, `phone`, the present-only amenity booleans (`dine_in`,
  `takeout`, `delivery`, `reservable`, `outdoor_seating`, `serves_*`, `good_for_*`, …),
  and slimmed `reviews` (≤5 × `{rating, text, language, publish_time, author}`).
- **Metadata:** `_transformed_at`, `_source_collection`.

## Why this transform differs from `tripadvisor_clean`

A strict EDA (`services/extract/google_places_api/eda-report.md`) showed Google data is
**already typed, valid, and geocoded**. So this transform has **no geocoding** (coordinates
are authoritative and copied verbatim) and **no type-repair** (ratings/counts arrive
typed). It does **projection + normalization + relevance flagging** instead:

1. **Projects** ~15 relevant fields out of the ~24 KB `details` blob (which is ~98% of
   bytes; a lean projection drops ~94%, mostly `photos` + `reviews`).
2. **Normalizes** `name` (whitespace + recase ALL-CAPS) and `city` (derived from the
   structured `addressComponents.locality`, recased, EN→IT `Milan`→`Milano`).
3. **Lifts structured address** (`street`, `street_number`, `postal_code`, `locality`,
   `province`, `country`) — a reliable lookup, not a regex parse.
4. **Classifies dining relevance** into `category_tier`
   (`restaurant` / `cafe_bar_bakery` / `non_dining` / `unknown`); `is_dining` = the first
   two (cafes, bars, bakeries, gelaterie are in scope).
5. **Flags** quality issues without deleting: `is_operational`, `has_rating`,
   `low_review`, `name_is_geographic`, `city_out_of_area`, plus a `flags[]` reason list.
6. **Derives features**: `photo_count`, `price_level`, `price_range`, amenity/service
   booleans (`dine_in`, `takeout`, `serves_*`, …), `has_website`/`has_phone`.
7. **Slims reviews** to ≤5 × `{rating, text, language, publish_time, author}` (full
   reviews stay in the raw collection for the optional LLM extension).

Canonical `rating`/`review_count` come from `details.*` (fetched later than the top-level
seed fields → fresher).

## Drop rules

- **Junk (default on):** records that are `name_is_geographic` **and** have no rating
  (≈22 inert placeholders — unusable name + nothing to compare) are dropped. Disable with
  `--keep-junk`. The raw collection still retains them.
- **Non-dining (default off):** `non_dining` records are kept and flagged; pass
  `--drop-non-dining` to exclude them instead. Hard scope filtering is otherwise deferred
  to entity resolution / the unified-dataset query.
- **Rerun convergence:** when a record is dropped this run, any stale copy left in
  `restaurants_clean_google` by a previous run with different drop settings is deleted
  (reported as `stale_deleted`) — so the destination always matches the current settings,
  not only after `--reset`.

`rating`/`review_count` prefer `details.*` (fresher) and coalesce to the top-level seed
value when details is missing. `low_review` is **count-only** (a record can be low-review
even with no rating). `is_dining = restaurant OR cafe_bar_bakery`.

## Run

```bash
docker compose up -d mongo          # destination + source live here
uv run dataman-load google          # ensure restaurants_raw_google is populated
uv run google-clean                 # clean the full dataset
uv run google-clean --limit 50      # quick slice
uv run google-clean --reset         # empty the destination first (destructive)
uv run google-clean --drop-non-dining --low-review 20
```

> **Editable-install gotcha** (see root `CLAUDE.md`): `uv run google-clean` runs a copied
> snapshot. After editing service code, run
> `uv sync --reinstall-package data-management-project` before smoke-testing the script.
> For verification prefer `uv run pytest` (reads source directly).

## Configuration

`DATAMAN_`-prefixed env (`config.py`); no Google API key required:

| setting | default |
|---|---|
| `DATAMAN_MONGO_URI` | `mongodb://localhost:27017` |
| `DATAMAN_MONGO_DB` | `dataman` |
| `DATAMAN_SOURCE_COLLECTION` | `restaurants_raw_google` |
| `DATAMAN_DESTINATION_COLLECTION` | `restaurants_clean_google` |
| `DATAMAN_LOW_REVIEW_THRESHOLD` | `10` (validated `>= 0`) |
| `DATAMAN_BATCH_SIZE` | `1000` (validated `> 0`) |
| `DATAMAN_DROP_NON_DINING` | `false` |
| `DATAMAN_DROP_JUNK` | `true` |

> **Env-collision note:** `DATAMAN_SOURCE_COLLECTION` / `DATAMAN_DESTINATION_COLLECTION`
> are shared (same `DATAMAN_` prefix) with the Tripadvisor transform. Rely on the
> per-service defaults above; only override deliberately. The transform refuses to run if
> source == destination.

## CleanReport

Returned and printed as JSON; feeds the stage-5 quality assessment. All relevance/quality
histogram counters reflect only *kept* (written) records; `read` is the input total.
Fields include: `read`, `written`, `missing_key`, `duplicates_collapsed`, `dropped_junk`,
`dropped_non_dining`, `stale_deleted`, `names_normalized`, `cities_canonicalized`,
`distinct_cities_before`/`distinct_cities_after`, `city_out_of_area`,
`address_parts_populated`, `tier_{restaurant,cafe_bar_bakery,non_dining,unknown}`,
`is_dining`, `name_is_geographic`, `not_operational`, `with_rating`/`without_rating`,
`low_review`, `photos_zero`.
