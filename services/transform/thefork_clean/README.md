# `thefork_clean` — TheFork Transform (T of ELT)

Mongo → Mongo transform: reads `restaurants_raw_thefork`, writes a lean, structured,
flag-annotated `restaurants_clean_thefork`, keyed and idempotent on `source_id`. The raw
collection is never mutated (immutable audit trail).

```bash
uv run thefork-clean                 # clean all raw records (full run also deletes delisted venues)
uv run thefork-clean --limit 50      # small slice while iterating (never sync-deletes)
uv run thefork-clean --reset         # empty the destination first (destructive)
uv run thefork-clean --low-review 20 # change the low-review flag threshold
```

> After editing this service, run `uv sync --reinstall-package data-management-project`
> before verifying through `uv run thefork-clean` (editable-install gotcha — see root
> `CLAUDE.md`). Tests read source directly and need no reinstall.

## What it does

Per the strict EDA (`services/extract/thefork_scraper/eda-report.md`), TheFork data is
**already typed, already geocoded, duplicate-free, and 100% dining**. So this transform is
**parse + structure + flag** — *not* type-repair, geocoding, dedup, or relevance filtering
(contrast `tripadvisor_clean` / `google_clean`). It resolves the dataset's First-Normal-Form
violations and does field hygiene:

- **Parse** `price_range "30 €"` → `avg_price_eur` (int); `discount` free-text →
  `discount_pct` (int, review-bleed strings nulled) + `has_discount`; `cuisine_type` →
  `cuisines[]` + `dietary_options[]` (an address accidentally stored in `cuisine_type` is
  rejected + flagged `invalid_cuisine_type`); opening hours → tidy `opening_hours[]` of
  `{day, opens, closes}` (prefers the pre-parsed `working_hours_structured`, falls back to
  the raw `working_days_hours` JSON string; past-midnight `"24:00"`–`"29:00"` folded to a
  valid `HH:MM` + `closes_next_day`).
- **Normalize** `restaurant_name` (whitespace + ALL-CAPS recase), `address` (strip the
  `I-` CAP prefix, fold EN `Milan`/`Italy`), `city` (`Milan` → `Milano`); lift `street` /
  `house_number` / `postal_code`; lift `tf_id` (the stable `-r<n>` venue id) as a
  join/blocking key.
- **Drop** the dead fields `phone_number`, `email`, `website`, `social_links` (all empty
  in the dataset) and the always-null nested review `title`; slim `reviews` to
  `{author_name, rating, text, date}` (≤15); pass `review_snippets` through as-is.
- **Flag (count-only, never delete):** `has_rating`, `has_review_count`, `low_review`
  (count-only, kept distinct from a *missing* count; may be scrape-incomplete),
  `has_discount`, `has_hours`, `has_reviews`, `rating_sample_divergent`, plus a `flags[]`
  reason list (`no_rating`, `missing_review_count`, `low_review`,
  `rating_sample_divergent`, `invalid_cuisine_type`).
- **Honest sample features** (clearly sample-based, never a stand-in for the platform
  numbers): `sample_size`, `sample_avg_rating`. Null `rating` is **not** backfilled from
  the nested-review sample (recent + biased).

`rating` stays on TheFork's native **0–10** scale (scale harmonisation is an integration
concern, out of scope here). Coordinates are copied verbatim (never recomputed).

## Output

A before/after `CleanReport` (read/written, parsed-field coverage, flags raised) is printed
as JSON and feeds the stage-5 quality assessment. Each clean doc carries `_id` (= `source_id`),
`_transformed_at`, and `_source_collection` metadata.

## Design

See `specs/thefork-elt-transform.md` for the spec and
`services/extract/thefork_scraper/eda-report.md` for the EDA.
