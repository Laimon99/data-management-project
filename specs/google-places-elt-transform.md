# Spec for google-places-elt-transform
branch: feature/google-places-elt-transform

## Summary

This feature establishes the **Transform (T) layer of the ELT pipeline** for the
**Google Places** source — the second source to get a transform, after Tripadvisor.
It deliberately **copies the `tripadvisor_clean` pattern** (PR #9): a single,
re-runnable, **Mongo → Mongo** transform service that reads the immutable raw
collection and writes a lean, typed, normalized clean collection, returning a
before/after `CleanReport`. It does **not** invent a new paradigm.

Today the project is **E** and **L** complete for Google: the Places-API extractor
(`services/extract/google_places_api`) produced the seed
(`data/raw/google_places/restaurants_seed.jsonl`, **10,808 records**), and the load
layer (`services/load/mongo`, `uv run dataman-load`) idempotently upserts those raw
records into the MongoDB collection `restaurants_raw_google`, keyed on the natural key
`place_id`. What is missing is the **T**: nothing yet projects, normalizes, or
scope-filters that raw data into a form the downstream stages can consume.

### Why Google's transform is *different* from Tripadvisor's

A strict EDA of the seed (full report:
[`services/extract/google_places_api/eda-report.md`](../services/extract/google_places_api/eda-report.md))
shows Google data is **already typed, valid, and geocoded** — the exact problems the
Tripadvisor transform existed to repair are **absent** here:

| Concern | Tripadvisor (PR #9) | Google (this spec) |
|---|---|---|
| Rating type | `"5,0"` decimal-comma string → parse | already a float in `[1.0,5.0]` (100% valid) → **copy** |
| Review count | `"(1.234 recensioni)"` → parse | already an int `≥ 1` (100% valid) → **copy** |
| `"NaN"` sentinels | pervasive → coerce to null | **none** |
| Coordinates | **missing** → geocode via Nominatim | **present & authoritative** (100% in Milan bbox) → **never recompute** |
| Address | free-text → fragile regex parse | `addressComponents` structured, present 100% → **lookup** |

So this transform **omits geocoding and type-repair entirely**. Instead it solves the
problems the EDA *did* surface for Google:

1. **Payload bloat** — the raw `details` blob is ~98% of bytes (~24 KB/record). A lean
   projection keeps only **5.8% of bytes (drops ~94%)**; the weight is almost entirely
   `photos` (35.5% of bytes, ≤10 photo-metadata objects) and `reviews` (24.9%, ≤5 full
   review texts). → **Project** ~15 relevant fields into a lean clean document.
   `reviews` is projected *out of the core clean doc* but is not junk — it is the input
   for the **optional LLM review-text extension**, which can read it from
   `restaurants_raw_google` when/if built.
2. **Scope dilution** — **96.4%** of records are in-scope dining venues
   (**53.7%** strict `restaurant` + **42.6%** `cafe_bar_bakery` — bars, cafes,
   bakeries, gelaterie, pubs, wine bars: **all in scope per project decision**). The
   problem is the **3.2% (≈345) hard `non_dining`** tier (gas stations, supermarkets,
   hotels, barber shops, swimming pools, cultural centers, shopping malls): **335 of 345
   carry real ratings** and would pollute the unified dataset and entity resolution.
   → **Classify into a 4-tier `category_tier` and set `is_dining = restaurant OR
   cafe_bar_bakery`**; only `non_dining`/`unknown` are out-of-scope noise.
3. **Junk records** — 26 records whose `name` is a geographic string
   (`"Metropolitan City of Milan"`, `"Milano"`), mostly `food_court` placeholders.
   **23 of the 26 have no rating** (inert: unusable name *and* nothing to compare); 3
   carry a rating; plus 337 closed venues (1 permanently). → **Flag all; drop the 23
   geographic-name-and-no-rating records** (see Resolved Decisions).
4. **`city` is unreliable** — 62 distinct values. A `"Milano"` (8960) vs `"Milan"` (109)
   EN/IT spelling split (the *only* EN/IT twin), **plus** values clearly outside the
   Milan metro despite 100% in-bbox coordinates (`Torino`, `Bergamo`, `Sasso Marconi`,
   `Vairano Patenora`, `MARTINA FRANCA`), casing junk (`paperino`), and non-city labels
   (`Area Industriale`, `Stazione`). → **Derive canonical `city` from structured
   `addressComponents.locality` + casing normalization, canonicalize the EN/IT twin to
   Italian (`Milano`), and flag out-of-area values.**
5. **`name` casing** — 4.36% ALL-CAPS (`"IN PIAZZA"`). → **Normalize** (title-case),
   preserving the structured raw in the audit collection.
6. **`rating`/`review_count` provenance** — top-level vs `details` count disagree in
   119 records (temporal drift). → **Pick one canonical field** — `details.*`, since the
   detail fetch is later than the seed capture (fresher).

The transform delivers **one service**, `google_clean`, operating strictly
**Mongo → Mongo** so the raw collection stays an immutable audit trail and the
transform is idempotently re-runnable. The resulting data lineage is:

```
restaurants_raw_google
   └─[google_clean]──►  restaurants_clean_google
                        (lean projection: typed ratings, normalized name/city,
                         structured address, authoritative coords, relevance flags)
```

It returns and logs a before/after **quality report** (`CleanReport`) that doubles as
evidence for the project's stage-5 quality-assessment deliverable.

### Why this matters downstream

- **Entity resolution (stage 3)** blocks by proximity + name/address similarity. It
  needs normalized `name`, structured `address`/`postal_code`, and authoritative
  `latitude`/`longitude` (Google's are the geographic backbone the other sources match
  *against*). It also benefits enormously from the **relevance flag**: matching a
  Tripadvisor restaurant against a Google *gas station* is a guaranteed false match.
- **Unified dataset (stage 4)** and the **mandatory queries** (rating difference > 1
  star, average rating by area) require typed `rating`/`review_count`, a canonical
  `city`/area, and a way to exclude non-restaurants.
- **Quality assessment (stage 5)** explicitly requires before/after metrics for
  duplicate handling, name normalization, address standardization, and low-review
  filtering — the `CleanReport` produces exactly these for Google.
- Cleaning **once** at the transform layer prevents every downstream consumer from
  re-deriving (and disagreeing on) relevance, canonical rating, and city spelling.

## Functional Requirements

### A. New service: `google_clean`

- **A1.** A new namespace-package service at `services/transform/google_clean`
  importable as `transform.google_clean`, following the existing
  `transform.tripadvisor_clean` module conventions (PEP 420 namespace package,
  `__init__.py`, `__main__.py`, `cli.py`, `config.py`, plus dedicated logic modules
  `cleaners.py` (pure field cleaning / classification), `transform.py` (Mongo
  orchestration), and a `README.md`). There is **no `geocode.py`** — Google
  coordinates are authoritative and are never recomputed.
- **A2.** A console entry point `google-clean` runnable via `uv run google-clean`,
  registered in `pyproject.toml` under `[project.scripts]`.
- **A3.** The service reads documents from the MongoDB collection
  `restaurants_raw_google` (the load layer's destination for Google) — **not** from the
  raw JSONL file on disk.
- **A4.** Cleaning/classification logic lives in `cleaners.py` as **pure functions**
  that take and return plain Python values, with no MongoDB, network, or I/O
  dependency, so they are independently unit-testable. At minimum:
  - **A4a. Field projection** — given a raw record, select only the fields the clean
    schema needs (see §A6) out of the ~24 KB `details` blob. The blob itself is **not**
    copied into the clean document.
  - **A4b. Rating / review-count pass-through (typed, canonical)** — copy `rating` as a
    `float | null` and `review_count` as an `int | null`. **No string parsing**
    (already typed). **Prefer `details.rating` / `details.userRatingCount`** (the detail
    fetch happens *after* the seed capture, so the detail values are fresher) but
    **coalesce to the top-level `rating` / `user_rating_count` when the detail field is
    missing** — there is exactly 1 record where `details.rating` is null while the
    top-level has a rating, and it must not be discarded. Review counts that arrive as a
    whole-valued float (e.g. `200.0`) are accepted as ints; out-of-range / non-whole /
    wrong-type values defensively become `null` rather than crash.
  - **A4c. Name normalization** — trim and collapse internal whitespace, and
    **case-normalize** ALL-CAPS names to a sensible title case (e.g. `"IN PIAZZA"` →
    `"In Piazza"`) while preserving already-mixed-case names. Title-casing is a
    **best-effort display heuristic** (`str.title()`): it can mishandle acronyms, brands,
    and some apostrophes/Italian casing — acceptable because the unmodified raw name
    remains in `restaurants_raw_google` for audit (no `*_raw` shadow field on the clean
    doc, matching the Tripadvisor decision). Whitespace-only → `null`.
  - **A4d. Structured address extraction (lookup, not parse)** — from
    `details.addressComponents` / `details.postalAddress`, populate `street`,
    `street_number`, `postal_code` (Italian 5-digit CAP), `locality`, `province`,
    `country` as separate keys, and retain a normalized full `address` string
    (`formatted_address`). Because `addressComponents` is present 100% of the time this
    is a reliable lookup; when a component is genuinely absent the sub-field is `null`.
  - **A4e. City canonicalization** — derive the canonical `city` from the structured
    `details.addressComponents.locality` (present ~100%) rather than trusting the flat
    `city` string, then casing-normalize it. Canonicalize the **only** EN/IT twin,
    `"Milan"` → `"Milano"` (Italian is canonical, per decision). Keep genuinely distinct
    metro-area municipalities (e.g. `"Sesto San Giovanni"`) intact — whether to keep
    them is an *integration*-stage decision, not this transform's. Set
    `city_out_of_area = true` when the resolved city is clearly outside the Milan metro
    (e.g. `Torino`, `Bergamo`, `Sasso Marconi`, `MARTINA FRANCA`) even though the
    coordinates are in-bbox (the flat `city` field has such defects). The original
    Places `city` value is recoverable from the raw collection.
  - **A4f. Dining-relevance classification** — classify each record by `primary_type`
    (and `types[]` as a tiebreaker) into a `category_tier` ∈
    `{restaurant, cafe_bar_bakery, non_dining, unknown}`, and derive
    `is_dining = (category_tier in {restaurant, cafe_bar_bakery})`. **Cafes, bars,
    bakeries, gelaterie, pubs and wine bars are in scope** (per project decision) — only
    `non_dining` and `unknown` are out-of-scope noise. The classifier is a pure function
    over a curated vocabulary (the EDA enumerated all 175 `primary_type` values):
    anything ending in `_restaurant` plus a curated extras set is `restaurant`; a curated
    cafe/bar/bakery/gelateria set is `cafe_bar_bakery`; a curated noise set
    (gas_station, supermarket, hotel, store, spa, food-retail like `candy_store`/`market`,
    …) is `non_dining`; null/unrecognised is `unknown`. **The `types[]` fallback is
    symmetric across all three tiers** (restaurant, cafe_bar_bakery, **and** non_dining) —
    so a record with a null/ambiguous `primary_type` but a `gas_station`/`hotel` tag
    classifies as `non_dining`, not `unknown`. In practice every seed record carries a
    dining or non-dining type tag, so `unknown` is empty. The 4-tier label is retained
    (not collapsed to a 2-way `is_dining`) so downstream analysis can still separate a
    trattoria from a gelateria.
  - **A4g. Junk / validity flagging** — derive boolean quality flags
    `name_is_geographic` (name equals a city/region/postcode string such as
    `"Metropolitan City of Milan"`), `is_operational` (`businessStatus ==
    "OPERATIONAL"`), `has_rating` (`rating is not null`), and `low_review`
    (`review_count is not null and review_count < low_review_threshold` — a **count-only**
    concept, independent of whether a rating is present). Each suppression-worthy
    condition is also recorded as a human-readable reason string in a `flags` list for
    auditability. **Drop rule:** a record that is **both** `name_is_geographic` **and**
    `not has_rating` (the ~22 inert placeholders — unusable name *and* nothing to
    compare) is excluded from the clean collection (it can contribute to no downstream
    stage; the raw record remains as audit). All other flagged records (closed,
    non-dining, low-review, rated-but-geographic-named) are **kept and flagged**, never
    deleted.
- **A5.** The transform writes one document per record into the collection
  `restaurants_clean_google` — the lean projection plus all derived fields/flags —
  keyed on `place_id` mapped to Mongo `_id`, using the same idempotent upsert strategy
  as the load layer (re-running must not create duplicates and must not error on
  existing keys). **Drop-convergence:** when a keyed record is *dropped* this run (junk,
  or `non_dining` under `--drop-non-dining`), any stale copy left in the destination by a
  previous run with different drop settings is **deleted**, so the destination always
  converges to what the current settings imply (not just on `--reset`). The source and
  destination collections must differ (guarded). Reported via `stale_deleted`.
- **A6.** The clean-document schema is (at minimum):

  | Field | Type | Source / rule |
  |---|---|---|
  | `_id` / `place_id` | str | natural key (passthrough) |
  | `name` | str \| null | A4c normalized |
  | `latitude`, `longitude` | float | authoritative passthrough (**never recomputed**) |
  | `address` | str \| null | normalized `formatted_address` |
  | `street`, `street_number`, `postal_code`, `locality`, `province`, `country` | str \| null | A4d structured |
  | `city` | str \| null | A4e canonical |
  | `rating` | float \| null | A4b canonical (from `details.*`) |
  | `review_count` | int \| null | A4b canonical (from `details.*`) |
  | `primary_type` | str \| null | passthrough |
  | `types` | list[str] | passthrough |
  | `category_tier` | str | A4f (`restaurant`/`cafe_bar_bakery`/`non_dining`/`unknown`) |
  | `is_dining` | bool | A4f |
  | `business_status` | str \| null | passthrough |
  | `is_operational` | bool | A4g |
  | `price_level` | str \| null | passthrough (categorical) |
  | `has_rating` | bool | A4g |
  | `low_review` | bool | A4g (vs `low_review_threshold`) |
  | `name_is_geographic` | bool | A4g junk flag |
  | `city_out_of_area` | bool | A4e (city outside Milan metro despite in-bbox coords) |
  | `flags` | list[str] | A4g reasons (may be empty) |
  | `photo_count` | int | feature: `len(details.photos)` (richness/popularity signal) |
  | `price_range` | obj \| null | feature: compacted `{start, end, currency}` |
  | `has_website`, `has_phone` | bool | feature/matching aid |
  | `website`, `phone` | str \| null | matching aids for entity resolution |
  | `dine_in`, `takeout`, `delivery`, `reservable`, `outdoor_seating`, `serves_*`, … | bool | features: snake-cased Google amenity/service flags (present-only) |
  | `reviews` | list[obj] | **slimmed** ≤5 × `{rating, text, language, publish_time, author}` (full reviews stay in raw for the LLM extension) |

- **A7.** The service returns and logs a `CleanReport` summarizing, at minimum: total
  input records, records written, duplicate `_id`s collapsed (expected 0), dropped junk,
  dropped non-dining, **stale docs deleted on rerun** (`stale_deleted`), names normalized
  (changed), cities canonicalized (e.g. Milano/Milan unified, count changed), distinct
  city count before/after, structured-address sub-fields populated, records per
  `category_tier`, `is_dining` count, `name_is_geographic` count, non-operational count,
  records with/without rating, and low-review count. **All relevance/quality histogram
  counters reflect only *kept* (written) records** (the dropped junk/non-dining records
  are excluded); `read` gives the input total. These feed the stage-5 deliverable's
  before/after metrics. *(Note: `duplicates_collapsed` is structurally ~0 because
  `place_id` is a perfect PK, so the stage-5 "duplicate removal" evidence comes from the
  EDA's name/coordinate-cluster analysis, not this counter.)*
- **A8.** The CLI accepts at least: `--limit N` (process only the first N records, for
  fast smoke testing without the full 10,808), `--reset` (clear the destination first),
  `--low-review N` (override threshold), `--drop-non-dining` (optional hard filter — see
  A9), `--keep-junk` (disable the default junk drop), and standard logging verbosity
  controls. (There is no `--drop` alias for `--reset` — it would be confusable with
  `--drop-non-dining`.)
- **A9. Relevance handling is flag-first; only inert junk is dropped by default.** By
  default the transform **flags but does not remove** non-dining, closed, and low-review
  records — they pass through to the clean collection, mirroring Tripadvisor's count-only
  low-review decision and keeping the maximum data available to entity resolution. The
  **one** default exclusion is the inert junk class (geographic name **and** no rating),
  which can serve no downstream stage; `--keep-junk` disables even that. Hard *filtering*
  of `non_dining` is a stage-3/stage-4 concern expressed via query/flag, with
  `--drop-non-dining` offered as an explicit opt-in convenience. Reruns converge (A5).
- **A10.** Configuration follows the existing `DATAMAN_`-prefixed settings convention
  (`config.py`), exposing: MongoDB connection settings (URI, database, source
  collection `restaurants_raw_google`, destination collection
  `restaurants_clean_google`), the `low_review_threshold` (validated `>= 0`),
  `batch_size` (validated `> 0`), and the `drop_non_dining` / `drop_junk` toggles. It
  must **not** require the Google API key (mirroring the load layer's and Tripadvisor
  transform's settings independence). **Env-collision note:** the Mongo URI/DB use the
  shared `DATAMAN_` prefix by design (one deployment), so `DATAMAN_SOURCE_COLLECTION` /
  `DATAMAN_DESTINATION_COLLECTION` are *shared* with the other transform services —
  exporting them in a common `.env` would point this service at non-Google collections.
  Mitigation: per-service defaults (relied on, not overridden lightly), a documented note
  in the README, and a runtime guard that refuses to run when source == destination.

### B. Explicitly NOT geocoding and NOT type-repairing

- **B1.** No Nominatim/geopy dependency and no `geocode.py`. Google `latitude`/
  `longitude` are copied verbatim and are **never** recomputed (project architecture:
  seed coordinates are the authoritative geographic backbone).
- **B2.** No decimal-comma / `"(N recensioni)"` / `"NaN"` parsing logic — the EDA
  confirms these patterns do not occur in Google data. Defensive `null`-coercion of an
  unexpectedly malformed value is allowed, but no source-specific string parsers are
  built.

### C. Cross-cutting / packaging

- **C1.** `pyproject.toml` is updated: register the `google-clean` script and add
  `services/transform/google_clean` to the wheel `force-include` list (the existing
  `transform` entry in ruff `known-first-party` already covers the import root).
- **C2.** The transform reuses a MongoDB connection approach consistent with
  `services/load/mongo` and `transform.tripadvisor_clean` (same driver, lazy client +
  explicit `ping`, same connection-settings style) rather than inventing a new one.
- **C3.** All new/changed code passes the project's pre-commit gates
  (`ruff --fix` + `ruff-format`) and targets `py311`.
- **C4.** Documentation is updated: the root `CLAUDE.md` tooling block and the relevant
  `docs/` files (e.g. `PIPELINE.md`, `etl-design.md`) reflect that the Google T-layer
  exists as a single Mongo→Mongo projection/normalization/flagging transform producing
  `restaurants_clean_google`. The inaccurate "`city` is always Milan" claim in
  `services/extract/google_places_api/dataset-schema.md` is corrected (62 municipalities).

## Possible Edge Cases

- **`rating`/`user_rating_count` null** (701 records, perfectly co-null) — clean doc
  carries `rating=null`, `review_count=null`, `has_rating=false`; must not crash and
  must not invent a 0.
- **Top-level vs `details` count disagreement** (119 records) — canonical field chosen
  deterministically (`details.*`, the fresher fetch); no double-write of both values.
- **`primary_type` null** (24 records) — `category_tier="unknown"`, `is_dining=false`,
  flagged; never crashes the classifier.
- **Name is a geographic string** (`"Metropolitan City of Milan"`, `"Milano"`,
  `"Novate milanese"`) → `name_is_geographic=true`, reason recorded; record still
  written (not silently dropped).
- **ALL-CAPS, single-char, or purely-numeric names** — recasing must not corrupt
  legitimate acronyms; single-char/numeric names are flagged but retained.
- **Non-ASCII names** (12.9%, legitimate accented/CJK) — preserved verbatim; **not**
  treated as a defect and **not** force-folded (folding, if ever needed, is an entity-
  resolution concern, not this transform's).
- **`city` spelling variants** (`Milano`/`Milan`) and 60 other municipalities —
  canonicalized consistently; an unrecognised municipality passes through trimmed,
  never crashes.
- **Missing `details.addressComponents` component** — affected structured sub-field is
  `null`; the normalized `address` string is always retained.
- **Duplicate `place_id`** (none observed; PK is perfect) — upsert collapses to one doc
  deterministically and the report counts the collapse.
- **Non-OPERATIONAL venues** (337, incl. 1 permanently closed) — `is_operational=false`,
  flagged; retention vs drop deferred to query/`--drop-*` flags.
- **Empty / missing source collection** — clear, non-crashing message and an all-zero
  report.
- **Mongo unreachable** — clear, actionable error (consistent with the load layer), not
  a raw stack trace.
- **`--limit` larger than available records** — process all available, no error.
- **Re-running after the raw collection grew** — new records added, existing ones
  updated in place, no duplicates (idempotency).

## Acceptance Criteria

- **AC1.** `uv run google-clean` reads `restaurants_raw_google` and populates
  `restaurants_clean_google` with lean, typed, normalized documents keyed on
  `place_id`.
- **AC2.** In the cleaned collection: `rating` is a float (or `null`), `review_count`
  is an int (or `null`), and the heavy `details` blob is **absent** (projection
  applied). `latitude`/`longitude` are present on every document and equal the raw
  values (never recomputed).
- **AC3.** Every cleaned document carries `category_tier` ∈
  `{restaurant, cafe_bar_bakery, non_dining, unknown}` and a boolean `is_dining`, plus
  the quality flags `is_operational`, `has_rating`, `low_review`, `name_is_geographic`.
- **AC4.** `city` is canonical: no document has `city == "Milano"` *and* another has
  `city == "Milan"` for the same place — the spelling split is resolved; metro-area
  municipalities are retained.
- **AC5.** Running `google-clean` twice yields the same document count and content
  (idempotent; no duplicates).
- **AC6.** By default no record is dropped (input count == output count); with
  `--drop-non-dining` only `non_dining` records are excluded and the report states how
  many.
- **AC7.** `google-clean` prints/logs a `CleanReport` containing before/after counts
  for: names normalized/recased, cities canonicalized and distinct-city before/after,
  structured-address fields populated, records per `category_tier`, non-dining count,
  junk (`name_is_geographic`) count, non-operational count, records with/without
  rating, and low-review count.
- **AC8.** No Nominatim/geopy dependency is added and no string-parsing of
  ratings/review-counts exists in the code (verified by absence; Google data needs
  neither).
- **AC9.** The pure cleaning/classification functions are unit-tested with no
  Mongo/network dependency; the Mongo path is exercised via `mongomock`, including
  idempotency and the flag/projection behavior. `uv run pytest` passes;
  `uv run pre-commit run --all-files` is clean.
- **AC10.** `pyproject.toml` registers `google-clean` and includes the new package in
  the wheel `force-include`; `CLAUDE.md` and the relevant `docs/` reflect the new Google
  transform; the `dataset-schema.md` "city always Milan" inaccuracy is corrected.

## Resolved Decisions

- **Geocoding — RESOLVED:** **none.** Google coordinates are authoritative and copied
  verbatim; there is no `geocode.py` and no Nominatim dependency. This is the defining
  difference from `tripadvisor_clean`. *(agreed — per project architecture)*
- **Type-repair — RESOLVED:** **none needed.** Ratings/counts are already correctly
  typed and in range (EDA: 100% valid); they are passed through, not parsed. *(agreed)*
- **Raw value preservation — RESOLVED:** rely on `restaurants_clean_google`'s sibling
  `restaurants_raw_google` as the audit trail; keep clean docs lean (no `*_raw` shadow
  fields), matching the Tripadvisor decision. *(agreed)*
- **Canonical rating/count source — RESOLVED:** use **`details.rating` /
  `details.userRatingCount`** as canonical — the detail fetch runs after the seed
  capture, so its values are fresher; do not carry the top-level duplicate. *(agreed)*
- **Dining scope — RESOLVED:** `restaurant` **and** `cafe_bar_bakery` (bars, cafes,
  bakeries, gelaterie, pubs, wine bars — 96.4% of the seed) are **in scope**;
  `is_dining` covers both. Only `non_dining` (3.2%) and `unknown` are noise. *(agreed)*
- **Relevance handling — RESOLVED:** **flag, don't delete** for `non_dining`
  (`category_tier` + `is_dining` + reasons); hard filtering is opt-in via
  `--drop-non-dining` and otherwise deferred to entity resolution / the unified-dataset
  query layer, so low-relevance records stay available. *(agreed — mirrors the
  low-review decision)*
- **Junk records — RESOLVED:** flag all geographic-name records; **drop** only those
  that are geographic-named **and** have no rating (23 inert placeholders) — they carry
  no usable name and no rating, so they can serve no downstream stage; raw retains them.
  The 3 geographic-named-but-rated records are kept and flagged. *(agreed)*
- **City canonical spelling — RESOLVED:** Italian is canonical → `"Milan"` becomes
  `"Milano"` (the only EN/IT twin). Derive `city` from structured
  `addressComponents.locality`, casing-normalize, and keep distinct municipalities
  (their drop is an integration-stage decision). Flag `city_out_of_area` values. *(agreed)*
- **Low-review threshold — RESOLVED:** configurable `low_review_threshold`, default
  `10` (matching the Tripadvisor transform), count-only. *(agreed)*
- **Record key — RESOLVED:** `_id` stays the natural key `place_id` (no new IDs minted;
  idempotency + raw↔clean join preserved). *(agreed)*

- **Tier boundary for food-retail — RESOLVED:** `candy_store` and `market` are
  classified `non_dining` (retail, not on-premise dining); `chocolate_shop` /
  `confectionery` stay in `cafe_bar_bakery`. Code and spec agree on this. *(agreed —
  handful of records; revisit only if noisy in entity resolution)*

## Cross-source clean contract (forward-looking)

The Google clean doc uses source-local field names (`name`, `review_count`, `place_id`),
as the Tripadvisor clean doc uses its own (`restaurant_name`, `total_review`,
`source_url`). Stage-3 entity resolution and the stage-4 unified table will need a small
**common contract** over the join-critical fields so downstream code does not branch per
source. The agreed minimal contract (to be materialized by an adapter at stage 3/4, **not**
by forcing every raw field into one shape now) is: `source`, `source_id`, `name`,
`address`, `city`, `latitude`, `longitude`, `rating`, `review_count`, `is_dining`,
`flags`. Each source-specific transform must be able to supply these (Google already
does, modulo the `source`/`source_id` aliasing). Documented here so the naming
divergence is a known, bounded adapter concern rather than a surprise.

## Open Questions

- **Permanently-closed venues:** drop in the transform, or only flag (`is_operational`)
  and let stage-5 decide? Current spec flags only. *(low priority — 1 record)*

## Out of Scope

- Cleaning/transforming **TheFork** — a follow-up spec copies this pattern.
- **Re-geocoding** Google coordinates — never; the seed coords are authoritative.
- **Entity resolution** (stage 3) — record linkage between platforms and the seed.
- **Unified dataset** construction (stage 4) and the **ClickHouse** integrated ratings
  table / mandatory analytical queries.
- The full **quality-assessment report** deliverable (stage 5) — this feature provides
  the `CleanReport` metrics that *feed* it, but not the consolidated assessment.
- **LLM-based** relevance filtering (CLAUDE.md mentions it as a seed-stage option); this
  transform uses a deterministic `primary_type` vocabulary instead. An LLM pass could be
  layered on later to refine the `unknown`/borderline tier.
- Changing the **extract** layer or the **load** layer behavior.
- Mongo authentication / deployment hardening (local dev runs without auth by design).

## Feature Testing Guidelines

Create test file(s) under `tests/transform/google_clean/` (consistent with
`pythonpath = ["services"]` and the project's `mongomock` dev dependency). Cover the
following without going too heavy:

- **Pure cleaners / classifiers (no Mongo, no network):**
  - `normalize_name`: collapse whitespace, trim; `"IN PIAZZA"` → `"In Piazza"`;
    already-mixed-case preserved; whitespace-only → `null`.
  - `canonical_city`: `"Milano"` and `"Milan"` → the single canonical spelling;
    `"Sesto San Giovanni"` passes through; unknown municipality passes through trimmed.
  - `extract_address_parts`: pull `street`/`street_number`/`postal_code`/`locality`/
    `province`/`country` from a typical `addressComponents`; missing component → `null`
    part while the full `address` is retained.
  - `classify_tier`: `*_restaurant` and curated extras → `restaurant`; bar/cafe/bakery
    set → `cafe_bar_bakery`; gas_station/supermarket/hotel/store → `non_dining`;
    `None`/unrecognised → `unknown`; `is_dining` derived correctly.
  - `quality_flags`: `name_is_geographic` true for `"Metropolitan City of Milan"` /
    `"Milano"`; `is_operational` from `businessStatus`; `has_rating` from `rating`;
    `low_review` vs threshold.
  - rating/count pass-through: float/int copied from `details.*`; `null` stays `null`
    and sets `has_rating=false`; `details.*` chosen over top-level on disagreement.
- **`google_clean` Mongo path (mongomock):**
  - Happy path: a small seeded `restaurants_raw_google` produces lean, typed,
    normalized docs (no `details` blob) in `restaurants_clean_google`, each with
    coordinates, `category_tier`, and flags.
  - Idempotency: running twice yields the same count and content (no duplicates).
  - Default run drops nothing (input count == output count); `--drop-non-dining`
    excludes only `non_dining` and the report counts them.
  - A `non_dining` fixture (e.g. a gas station with a rating) is written, flagged, and
    counted — not silently dropped.
  - A geographic-name junk fixture is flagged `name_is_geographic` and retained.
  - `CleanReport` fields reflect the seeded fixture's expected counts (tier histogram,
    cities canonicalized, names recased, junk/non-operational/low-review counts).
- **Config wiring:** the service builds its settings from `DATAMAN_`-prefixed env
  without requiring the Google API key.
