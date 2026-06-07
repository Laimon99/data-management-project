# Spec for thefork-elt-transform
branch: feature/thefork-elt-transform

> **Updated for the new dataset version (scraped 2026-06-06).** A teammate re-scraped
> TheFork; see [`docs/the_fork_migration/DATASET_CHANGES.md`](../docs/the_fork_migration/DATASET_CHANGES.md).
> The new run keeps the same **record count (1,344)** — though only 1,338 restaurants
> overlap, with **6 venues dropped and 6 added** (so reruns must converge on the current
> key set, see §A) — and: **reviews tripled** (cap 5→15), **coordinates are now complete**
> (1,344/1,344, all `detail_scraped=true`), it added a pre-parsed
> **`working_hours_structured`** field, **`website` is gone** (25→0) and the new
> **`social_links`** field is empty everywhere, and **`cuisine_type` is now effectively
> atomic** (the previous multi-cuisine + dietary tags were lost). This spec reflects that
> version; the EDA file documents the original analysis and the deltas.

## Summary

This feature adds **`thefork_clean`**, the **Transform (T) layer of the ELT pipeline**
for the TheFork source, completing the trio alongside `tripadvisor_clean` (PR #9) and
`google_clean` (PR #10). It operates strictly **Mongo → Mongo**: it reads the raw
collection `restaurants_raw_thefork` (populated by the load layer from
`data/raw/thefork/thefork_milan_restaurants_enriched.json`, **1,344 records**) and writes
a lean, structured, flag-annotated collection `restaurants_clean_thefork`. The raw
collection stays an immutable audit trail and the transform is re-runnable.

A strict EDA — [`services/extract/thefork_scraper/eda-report.md`](../services/extract/thefork_scraper/eda-report.md) —
established that TheFork data is **already typed**, **already geocoded** (now 100% present,
inside the Milan bbox), **duplicate-free** (verified: the lone fuzzy name match is two real
branches ~5 km apart), and **100% dining**. Therefore this transform is deliberately **NOT**
the type-repair-and-geocode work Tripadvisor needed, and **NOT** the relevance-filtering
work Google needed. Its job is **parse → structure → flag**:

1. **Resolve the dataset's First-Normal-Form violations** — rich fields the scraper left as
   serialized structures or unit-bearing strings (`price_range` as `"30 €"`, `discount` as
   free Italian promo text, opening hours as schema.org objects, `cuisine_type` as a
   comma-CSV) are parsed into typed, queryable fields.
2. **Field hygiene** — drop the fields that are empty for every record, and normalize the
   text fields.
3. **Honest quality flags & features** — count-only flags (never deleting rows) and
   clearly sample-labeled review features, plus a before/after `CleanReport` that feeds
   the project's stage-5 quality-assessment deliverable.

The resulting data lineage is:

```
restaurants_raw_thefork
   └─[thefork-clean]──►  restaurants_clean_thefork   (parsed/typed fields + flags)
```

### Why this matters

- The raw TheFork fields bury values in unit-bearing/serialized strings (1NF violations),
  so no downstream consumer can query by price, read a discount, or read opening hours
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
  transforms (`[project.scripts]`, wheel force-include, ruff `known-first-party`).
- Mongo → Mongo, reusing the established settings pattern (`DATAMAN_`-prefixed, Mongo
  fields only — no scraper/API secrets).
- Reads `restaurants_raw_thefork`, writes `restaurants_clean_thefork`, **keyed/idempotent
  on `source_id`** (re-running must not duplicate). A source==destination guard, as in
  `google_clean`.
- **Rerun convergence:** on a full run (no `--limit`), destination docs whose `source_id`
  no longer exists in the source are deleted, so venues delisted upstream (the 6 dropped)
  do not linger. A `--limit` run is intentionally partial and never sync-deletes.
- Pure cleaning/parsing functions live in `cleaners.py` (no Mongo, no I/O — unit testable
  in isolation), orchestrated by `transform.py`; CLI in `cli.py`. Follows the module
  layout of `tripadvisor_clean` / `google_clean`.

### B. Parse the 1NF-violation fields (the core value)

- **`price_range`** (`"30 €"`) → numeric **`avg_price_eur`** (int). All 1,344 parse;
  the lone `"1 €"` placeholder is parsed as-is (1).
- **`discount`** (free Italian text) → **`discount_pct`** (int | null) **plus**
  **`has_discount`** (bool). The percentage is extracted **only** from clean promo
  patterns; values that are review text bled into the field (newline, over-long, or
  multiple distinct percentages) yield `discount_pct = null` while `has_discount` stays
  true. (New version: discount coverage dropped to 650, likely promo expiry.)
- **Opening hours → tidy `opening_hours`** — a list of `{day, opens, closes}` with
  English day names. **Prefer the scraper's pre-parsed `working_hours_structured`** (a list
  of schema.org `OpeningHoursSpecification` objects, 855/1,344); **fall back to `json.loads`
  of the raw `working_days_hours` string** when the structured field is absent. One entry is
  emitted per day in a spec's `dayOfWeek` list, preserving split (lunch/dinner) shifts.
  **Past-midnight times** (`"24:00"`–`"29:00"`, ~1,188 slots in this scrape) are **folded to
  valid `HH:MM` with `closes_next_day: true`**, so every emitted `opens`/`closes` is a real
  clock time (not a `"26:00"` string that downstream parsers choke on). (Google's clean
  output carries no hours field, so there is nothing to align to.)
- **`cuisine_type`** (comma-CSV) → **`cuisines`** (list) **plus** **`dietary_options`**
  (list lifted from the diet/religious tokens: vegetarian, vegan, gluten-free, organic,
  halal, kosher); the noise token `"Solo in Italiano"` is dropped. A `cuisine_type` value
  that is actually an **address leak** (contains a CAP, `Milano`, or a street prefix — e.g.
  `"Corso Garibaldi, 111, Milano"`, 1 record) is rejected to `cuisines = []` and flagged
  `invalid_cuisine_type` rather than minting fake facets. **Note:** in the new version
  `cuisine_type` is effectively *atomic* (only 1 multi-value record; dietary tags almost
  entirely lost — `dietary_options` is populated in just 3/1,344), so `cuisines` is usually
  a single-element list. The split is kept anyway — correct, harmless, and future-proof if a
  later re-scrape restores multi-value cuisines.

### C. Normalize & structure

- **`restaurant_name`** — collapse whitespace and best-effort recase the ALL-CAPS names to
  title case; keep legitimate accented/CJK characters.
- **`address`** — normalize (strip the `I-` CAP prefix, fold the EN `Milan`/`Italy` forms
  to `Milano`/`Italia`, collapse whitespace/commas) and best-effort structured split into
  **`street`** (name), **`house_number`** (the civic number — kept as its own field so the
  dominant `"Via X, 13, …"` shape does not silently drop it; ~1,295 records), and
  **`postal_code`** (all CAPs are valid Milan `20xxx`). The normalized full `address` stays
  the source of truth; any sub-field that cannot be confidently parsed is null.
- **`city`** — normalize the constant EN `"Milan"` to canonical `"Milano"`.
- **`tf_id`** — extract the stable `-r<n>` venue id from `source_id` and store it as a
  first-class join/blocking field (the analogue of Tripadvisor's `ta_location_id`).

### D. Field hygiene — drop

- **Drop** `phone_number`, `email`, `website`, and `social_links` (all empty for every
  record in this version) and the nested review **`title`** (100% null) from the slimmed
  review objects.
- The raw composite/serialized strings (`price_range`, `discount`, `cuisine_type`,
  `working_days_hours`, `working_hours_structured`) are **not** copied into the clean doc
  (they are replaced by the parsed fields); they remain in the raw collection.

### E. Pass-through fields (authoritative / already clean)

`latitude`, `longitude` (now complete), `rating` (kept on its native 0–10 scale; nulls
kept), `review_count` (best-effort, possibly scrape-incomplete), `photo_count`,
`restaurant_url`, `source`, `scraped_at`, `source_page_number`, `detail_scraped`, and
`review_snippets` (**kept as-is / passthrough**). `reviews` is slimmed to
`{author_name, rating, text, date}` per review (≤15; per-review `rating` stays on the
native 0–10 scale).

### F. Flags & honest features (count-only — never delete rows)

- Boolean flags: **`has_rating`**, **`has_review_count`**, **`low_review`** (count-only
  threshold, kept strictly distinct from a *missing* count; documented as *possibly
  scrape-incomplete*, because rating/count missingness is MAR — it rose with listing-page
  depth in the EDA), **`has_discount`**, **`has_hours`**, **`has_reviews`**.
- A **`flags`** list of reason strings (mirrors `google_clean`): any of `no_rating`,
  `missing_review_count`, `low_review`, `rating_sample_divergent`, `invalid_cuisine_type`;
  empty when none apply.
- Clearly sample-labeled review features that **never substitute** the platform values:
  **`sample_size`** (= number of nested reviews kept), **`sample_avg_rating`** (mean of
  nested review ratings), **`rating_sample_divergent`** (true where the platform `rating`
  differs from the nested-review sample mean by > 1).

### G. Reporting

- Return and log a before/after **`CleanReport`**: input/output counts, per-parsed-field
  coverage (`avg_price_eur` / `opening_hours` / `discount_pct` / cuisines / dietary), flags
  raised (`with_rating` / `without_rating` / `low_review` / `rating_sample_divergent`), and
  discount-noise dropped — feeding the stage-5 quality deliverable.

### H. Input handling

- Consume the single raw collection sourced from `…_enriched.json`. (The `…_enriched.json`
  and `…_normalized_partial.json` files are byte-for-byte identical; the `…_mac_slots_*`
  intermediate and the `…merge_report.json` are not the dataset.)

## Possible Edge Cases

- **`discount` review-bleed** — promo strings that contain review prose or multiple
  percentages must resolve to `discount_pct = null` (not a wrong number scraped out of a
  sentence) while still counting as `has_discount`.
- **Null vs zero** — `discount` null means "no promo" (legitimate), distinct from a parse
  failure; `review_count == 0` is valid, not missing.
- **Opening-hours source** — prefer `working_hours_structured`; fall back to the raw
  `working_days_hours` string; malformed/empty either way → `[]` (and `has_hours=false`).
  Past-midnight times (`"24:00"`–`"29:00"`) must be folded to a valid `HH:MM` with
  `closes_next_day`, never emitted as an out-of-range clock string.
- **`cuisine_type` address leak** — when the field holds an address (CAP / `Milano` /
  street prefix), reject it (`cuisines=[]`) and flag `invalid_cuisine_type` rather than
  splitting it into fake cuisine values.
- **Rerun after upstream churn** — a full rerun must delete clean docs for the 6 delisted
  venues (converge to the current raw key set); a `--limit` run must not.
- **Partial / non-canonical addresses** — some deviate from the canonical 4-comma shape
  (missing civic number, `7/9` ranges, abbreviations like `V.le`); structured sub-fields
  must degrade to null rather than mis-parse.
- **Rating present, count absent (and vice-versa)** — `rating` and `review_count` are not
  co-null; flags must reflect each independently. Null `rating` must **not** be imputed.
- **Empty review/snippet lists** — must serialize as `[]`, not null.
- **`cuisine_type`** — may be a single token, multi-value, purely dietary, or null;
  `cuisines` and `dietary_options` must each handle empty results.
- **Idempotency / rerun convergence** — re-running converges (no duplicates); `--reset`
  clears the destination when the upstream raw set changes (6 added / 6 dropped venues).
- **Heterogeneous coordinate precision** is a provenance signal, not an error — passed
  through unchanged (coordinates are never recomputed).

## Acceptance Criteria

- `uv run thefork-clean` reads `restaurants_raw_thefork` and writes
  `restaurants_clean_thefork`, idempotent on `source_id` (a second run produces no
  duplicates and no content changes beyond run metadata). On a **full run**, clean docs for
  venues removed from the source are deleted (`stale_deleted`); a `--limit` run does not.
- The 1NF-violation fields are parsed: `avg_price_eur` (numeric), `opening_hours` (tidy
  per-day array; every `opens`/`closes` a **valid `HH:MM`**, past-midnight folded with
  `closes_next_day`), `discount_pct` + `has_discount`, `cuisines` + `dietary_options`
  (arrays; address-leak `cuisine_type` rejected + flagged).
- `phone_number`, `email`, `website`, `social_links`, and nested review `title` are absent
  from clean docs.
- `tf_id`, `street`, `house_number`, `postal_code` are present where parseable; `city` is
  `"Milano"`.
- `rating` remains on the 0–10 scale; null ratings are **not** backfilled from nested
  reviews.
- Count-only flags and the `flags[]` reason list are populated; no rows are deleted.
- A `CleanReport` with before/after counts and per-field coverage is returned and logged.
- `uv run pytest` passes (new tests included); `uv run pre-commit run --all-files` is
  clean (ruff + ruff-format).

## Open Questions (resolved)

- **`low_review` threshold** → default 10 (matches `google_clean`); overridable via
  `--low-review`.
- **`opening_hours` day names** → mapped to canonical English (`monday`…`sunday`).
- **`_id`** → `source_id` (matches how the load layer keys `restaurants_raw_thefork`).

## Out of Scope

- Geocoding (coordinates are authoritative and already present).
- Numeric type-coercion of `rating` / `review_count` (already typed).
- Backfilling null ratings from nested reviews (the ≤15 sample is recent and biased).
- Deduplication (the dataset is verified duplicate-free).
- Non-dining relevance filtering (the slice is 100% Milan restaurants).
- Cross-source rating-scale harmonisation (`rating_5 = rating/2` is explicitly skipped as
  an integration concern), entity resolution, the unified dataset, and any `→ ClickHouse`
  ETL.
- Translating Italian cuisine/review text to English (it is source data; kept verbatim).
- Restoring the lost `website` / multi-cuisine / dietary data — that is an upstream scraper
  fix, not a transform concern (see `docs/the_fork_migration/`).

## Feature Testing Guidelines

Test file(s) under `tests/transform/thefork_clean/` with meaningful but not excessive
coverage:

- **Pure cleaners** (`test_clean_cleaners.py`):
  - `price_range` parsing (`"30 €"` → 30; the `"1 €"` outlier; malformed → null).
  - `cuisine_type` split into `cuisines` + `dietary_options`; atomic single value; dietary
    lift + dedup; `"Solo in Italiano"` dropped; null input.
  - `tidy_opening_hours` — prefers structured, falls back to raw string, maps day names,
    keeps split shifts and past-midnight times, malformed/empty → `[]`.
  - `discount` → `discount_pct` for clean patterns; review-bleed / multi-percent → null;
    null → `has_discount=False`.
  - `address` normalization (`I-` prefix strip, EN `Milan`/`Italy` fold) and structured
    `street`/`postal_code` split incl. missing-CAP inputs.
  - `tf_id` extraction; `name` whitespace + ALL-CAPS recase; `city` normalization.
  - `slim_reviews` (cap 15, drops `title`); `sample_avg_rating`; flag derivation incl.
    no rating-backfill.
- **Mongo orchestration** (`test_clean_transform.py`, using `mongomock`):
  - Happy-path transform into clean docs with the expected schema (structured hours, parsed
    price/discount, `_source_collection`).
  - Idempotency keyed on `source_id`; `--reset` clears the destination; source==destination
    raises; settings need no secrets and reject invalid values.
  - Dropped fields absent; `review_snippets` passthrough; reviews slimmed (no `title`).
  - Discount review-bleed → `discount_pct` null but `has_discount` true.
  - `CleanReport` counters (rating present/absent, low_review, parsed-field coverage) correct.
