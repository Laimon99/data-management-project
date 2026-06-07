# Spec for thefork-elt-transform
branch: feature/thefork-elt-transform

## Summary

This feature adds **`thefork_clean`**, the **Transform (T) layer of the ELT pipeline**
for the TheFork source, completing the trio alongside `tripadvisor_clean` (PR #9) and
`google_clean` (PR #10). It operates strictly **Mongo → Mongo**: it reads the raw
collection `restaurants_raw_thefork` (populated by the load layer from
`data/raw/thefork/thefork_milan_restaurants_enriched.json`, **1,344 records**) and writes
a lean, structured, flag-annotated collection `restaurants_clean_thefork`. The raw
collection stays an immutable audit trail and the transform is re-runnable.

A strict EDA — [`services/extract/thefork_scraper/eda-report.md`](../services/extract/thefork_scraper/eda-report.md) —
established that TheFork data is **already typed**, **already geocoded** (99.8% present,
100% inside the Milan bbox), **duplicate-free** (verified: the lone fuzzy name match is
two real branches ~5 km apart), and **100% dining**. Therefore this transform is
deliberately **NOT** the type-repair-and-geocode work Tripadvisor needed, and **NOT** the
relevance-filtering work Google needed. Its job is **parse → structure → flag**:

1. **Resolve the dataset's First-Normal-Form violations** — several rich fields were left
   by the scraper as serialized structures or multi-value strings (`price_range` as
   `"30 €"`, `cuisine_type` as a comma-CSV, `working_days_hours` as stringified
   schema.org JSON, `discount` as free Italian promo text). These are parsed into typed,
   queryable fields.
2. **Field hygiene** — drop the fields that are 100% null, demote a mislabeled field, and
   normalize text fields.
3. **Honest quality flags & features** — count-only flags (never deleting rows) and
   clearly sample-labeled review features, plus a before/after `CleanReport` that feeds
   the project's stage-5 quality-assessment deliverable.

The resulting data lineage is:

```
restaurants_raw_thefork
   └─[thefork-clean]──►  restaurants_clean_thefork   (parsed/typed fields + flags)
```

### Why this matters

- The raw TheFork fields conflate multiple values in single strings (1NF violations), so
  no downstream consumer can filter by cuisine, query by price, or read opening hours
  without re-implementing fragile parsing. Cleaning **once**, at the transform layer,
  prevents every consumer from re-deriving (and disagreeing on) the same logic.
- **Quality assessment (stage 5)** explicitly requires before/after metrics for name
  normalization, address standardization, and low-review filtering — the `CleanReport`
  produces exactly these for TheFork.
- It mirrors the established `tripadvisor_clean` / `google_clean` package shape, keeping
  the three sources symmetric and maintainable.

This spec covers **only** within-dataset cleaning and feature engineering for TheFork.
Cross-source entity resolution, the unified dataset, and rating-scale harmonisation are
later pipeline stages and are out of scope.

## Functional Requirements

### A. New service: `thefork_clean`

- A new package `services/transform/thefork_clean` exposing a console script
  (`uv run thefork-clean`), registered in `pyproject.toml` mirroring the other two
  transforms (`[project.scripts]`, wheel `packages`, ruff `known-first-party`).
- Mongo → Mongo, reusing the established settings pattern (`DATAMAN_`-prefixed, Mongo
  fields only — it must not require the Google API key).
- Reads `restaurants_raw_thefork`, writes `restaurants_clean_thefork`, **keyed/idempotent
  on `source_id`** (re-running must not duplicate). A source==destination guard, as in
  `google_clean`.
- Pure cleaning/parsing functions live in a `cleaners.py` (no Mongo, no I/O — unit
  testable in isolation), orchestrated by a `transform.py`; CLI in `cli.py`. Follows the
  module layout of `tripadvisor_clean` / `google_clean`.

### B. Parse the 1NF-violation fields (the core value)

- **`price_range`** (`"30 €"`) → numeric **`avg_price_eur`** (int). All 1,344 parse;
  the lone `"1 €"` placeholder is parsed as-is (1).
- **`cuisine_type`** (comma-CSV) → **`cuisines`** (list of cuisine strings) **plus**
  **`dietary_options`** (list lifted from the diet/religious tokens: vegetarian, vegan,
  gluten-free, organic, halal, kosher). The non-cuisine noise token `"Solo in Italiano"`
  is dropped from both.
- **`working_days_hours`** (stringified schema.org JSON) → **`opening_hours`**: a tidy
  per-day array of `{day, opens, closes}` with normalized day names. (Google's clean
  output carries no hours field, so there is nothing to align to; the tidy per-day shape
  is the chosen target.)
- **`discount`** (free Italian text) → **`discount_pct`** (int | null) **plus**
  **`has_discount`** (bool). The percentage is extracted **only** from clean promo
  patterns; values that are review text bled into the field (≈16, e.g. embedded `\n`,
  sentence fragments) yield `discount_pct = null`.

### C. Normalize & structure

- **`restaurant_name`** — collapse whitespace and best-effort recase the ALL-CAPS names
  (26) to title case; keep legitimate accented/CJK characters.
- **`address`** — normalize (strip the `I-` CAP prefix on 65 records, fold the EN
  `Milan`/`Milan, Italy` forms on 19 records to `Milano`, collapse whitespace/commas) and
  best-effort structured split into **`street`** and **`postal_code`** (all CAPs are
  valid Milan `20xxx`). The normalized full `address` stays the source of truth; any
  sub-field that cannot be confidently parsed is null.
- **`city`** — normalize the constant EN `"Milan"` to canonical `"Milano"`.
- **`tf_id`** — extract the stable `-r<n>` venue id from `source_id` and store it as a
  first-class join/blocking field (the analogue of Tripadvisor's `ta_location_id`).

### D. Field hygiene — drop / demote

- **Drop** `phone_number` and `email` (both 100% null) and the nested review **`title`**
  (100% null) from the slimmed review objects.
- **Demote** `website` → **`michelin_url`** (the 25 present values are all
  `guide.michelin.com` partner links, not the restaurant's own site) with a
  **`has_michelin_guide`** boolean.
- The raw composite/serialized strings (`price_range`, `discount`, `cuisine_type`,
  `working_days_hours`) are **not** copied into the clean doc (they are replaced by the
  parsed fields); they remain in the raw collection.

### E. Pass-through fields (authoritative / already clean)

`latitude`, `longitude` (3 null kept), `rating` (kept on its native 0–10 scale; nulls
kept), `review_count` (best-effort, possibly scrape-incomplete), `photo_count`,
`restaurant_url`, `source`, `scraped_at`, `source_page_number`, `detail_scraped`, and
`review_snippets` (**kept as-is / passthrough**). `reviews` is slimmed to
`{author_name, rating, text, date}` per review (the per-review `rating` stays on the
native 0–10 scale).

### F. Flags & honest features (count-only — never delete rows)

- Boolean flags: **`has_rating`**, **`low_review`** (count-only threshold; documented as
  *possibly scrape-incomplete*, because rating/count missingness is MAR — it rises with
  listing-page depth), **`has_discount`**, **`has_michelin_guide`**,
  **`scrape_incomplete`** (the 3 `detail_scraped=False` records).
- A **`flags`** list of reason strings (mirrors `google_clean`), empty when none apply.
- Clearly sample-labeled review features that **never substitute** the platform values:
  **`sample_size`** (= number of nested reviews), **`sample_avg_rating`** (mean of nested
  review ratings), **`rating_sample_divergent`** (true for the ~164 records where the
  platform `rating` differs from the nested-review sample mean by > 1).

### G. Reporting

- Return and log a before/after **`CleanReport`**: input/output counts, per-parsed-field
  coverage (e.g. how many `avg_price_eur` / `opening_hours` / `discount_pct` parsed),
  flags raised, and dead fields dropped — feeding the stage-5 quality deliverable.

### H. Input handling

- Consume the single raw collection sourced from `…_enriched.json`. (The two raw files
  `…_enriched.json` and `…_normalized_partial.json` are byte-for-byte identical, so the
  partial copy is ignored.)

## Possible Edge Cases

- **`discount` review-bleed** — promo strings that actually contain review prose or
  multiple percentages must resolve to `discount_pct = null`, not a wrong number scraped
  out of a sentence.
- **Null vs zero** — `discount` null means "no promo" (legitimate, 395 records), distinct
  from a parse failure; `review_count == 0` (4 records) is valid, not missing.
- **Partial / non-canonical addresses** — 154 deviate from the canonical 4-comma shape
  (missing civic number, `7/9` ranges, `(ang. via …)` annotations, abbreviations like
  `V.le`); structured sub-fields must degrade to null rather than mis-parse.
- **Missing coordinates / un-scraped rows** — the 3 `detail_scraped=False` rows lack
  lat/lon, hours, and reviews; they must be kept and flagged, not dropped.
- **Rating present, count absent (and vice-versa)** — `rating` and `review_count` are not
  co-null; flags must reflect each independently.
- **Empty review/snippet lists** — must serialize as `[]`, not null.
- **`cuisine_type` mixed tokens** — a record can be purely dietary tags (no real
  cuisine), purely cuisines, or `null`; `cuisines` and `dietary_options` must each handle
  empty results.
- **Idempotency / rerun convergence** — re-running with changed parsing/flag settings
  must converge (no stale duplicated docs).
- **Heterogeneous coordinate precision** (3–15 decimal places) is a provenance signal,
  not an error — must be passed through unchanged (coordinates are never recomputed).

## Acceptance Criteria

- `uv run thefork-clean` reads `restaurants_raw_thefork` and writes
  `restaurants_clean_thefork`, idempotent on `source_id` (a second run produces no
  duplicates and no spurious changes).
- All four 1NF-violation fields are parsed: `avg_price_eur` (numeric), `cuisines` +
  `dietary_options` (arrays), `opening_hours` (tidy per-day array), `discount_pct` +
  `has_discount`.
- `phone_number`, `email`, and nested review `title` are absent from clean docs;
  `website` appears only as `michelin_url` + `has_michelin_guide`.
- `tf_id`, `street`, `postal_code` are present where parseable; `city` is `"Milano"`.
- `rating` remains on the 0–10 scale; the 44 null ratings are **not** backfilled from
  nested reviews.
- Count-only flags and the `flags[]` reason list are populated; no rows are deleted.
- A `CleanReport` with before/after counts and per-field coverage is returned and logged.
- `uv run pytest` passes (new tests included); `uv run pre-commit run --all-files` is
  clean (ruff + ruff-format).

## Open Questions

- Final `low_review` threshold value (default to match `google_clean`, e.g. 10, unless a
  TheFork-specific value is preferred).
- Exact `opening_hours` day-name normalization target (keep Italian day names vs map to a
  canonical/English vocabulary).
- Whether `_id` should be `source_id` or `restaurant_url` (they are 1:1) — pick whichever
  matches how the load layer keys `restaurants_raw_thefork`.

## Out of Scope

- Geocoding (coordinates are authoritative and already present, 100% in-bbox).
- Numeric type-coercion of `rating` / `review_count` (already typed).
- Backfilling null ratings from nested reviews (the ≤5 sample is recent and biased — p95
  divergence 1.5; 164 rows > 1 apart).
- Deduplication (the dataset is verified duplicate-free).
- Non-dining relevance filtering (the slice is 100% Milan restaurants).
- Cross-source rating-scale harmonisation (`rating_5 = rating/2` is explicitly skipped as
  an integration concern), entity resolution, the unified dataset, and any `→ ClickHouse`
  ETL.
- Translating Italian cuisine/review text to English (it is source data; kept verbatim).

## Feature Testing Guidelines

Create test file(s) under `tests/transform/thefork_clean/` with meaningful but not
excessive coverage:

- **Pure cleaners** (`tests/transform/thefork_clean/test_clean_cleaners.py`):
  - `price_range` parsing (`"30 €"` → 30; the `"1 €"` outlier; malformed → null).
  - `cuisine_type` split into `cuisines` + `dietary_options`; dietary-only and null
    inputs; `"Solo in Italiano"` dropped.
  - `working_days_hours` parse to the tidy per-day array; null and (defensively)
    malformed inputs.
  - `discount` → `discount_pct` for clean patterns; review-bleed / multi-percent strings
    → null; null → `has_discount=False`.
  - `address` normalization (`I-` prefix strip, EN `Milan`→`Milano`) and structured
    `street`/`postal_code` split incl. non-canonical inputs.
  - `tf_id` extraction from `source_id`; `name` whitespace + ALL-CAPS recase; `city`
    normalization.
  - Flag derivation: `has_rating`, `low_review` (count-only), `has_discount`,
    `has_michelin_guide`, `scrape_incomplete`; `sample_avg_rating` / `rating_sample_divergent`.
- **Mongo orchestration** (`tests/transform/thefork_clean/test_clean_transform.py`, using
  `mongomock`):
  - Happy-path transform of a small raw fixture into clean docs with the expected schema.
  - Idempotency / rerun convergence keyed on `source_id`.
  - Dropped fields absent; `website`→`michelin_url`; `review_snippets` passthrough;
    reviews slimmed (no `title`).
  - Un-scraped (`detail_scraped=False`) and zero-review records kept and flagged, not
    dropped.
  - `CleanReport` before/after counts and per-field coverage are correct.
