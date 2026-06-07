# Spec for tripadvisor-clean-parity
branch: feature/tripadvisor-clean-parity

## Summary

This feature brings `transform.tripadvisor_clean` up to the same analytical and
operational standard as `google_clean` and `thefork_clean`.

The current Tripadvisor transform is useful, but narrow: it repairs the raw string
types (`rating`, `total_review`, `"NaN"` sentinels), normalizes name/address, extracts
basic address parts, geocodes via Nominatim, and writes
`restaurants_clean_tripadvisor`. That is the right foundation, but it leaves several
source-specific fields unstructured and does not expose per-record quality flags the
way Google and TheFork do.

The raw Tripadvisor dataset has 7,539 unique records keyed by `source_url`, with no
missing keys and no raw duplicates. Several rich fields are present and parseable:

- `number_photo_uploaded`: 5,949 present; parseable as an integer feature.
- `price_range`: 5,101 present; only a small controlled set of euro bands.
- `cuisine_type`: 5,859 present; comma-separated values, 3,730 multi-cuisine rows.
- `working_days_hours`: 5,096 present; all observed values look structurally parseable.
- `review`: 6,683 rows with 75,296 review objects; review text needs slim projection and
  display-text cleanup.

This feature does not change the basic ELT shape. It keeps a single Mongo -> Mongo
transform:

```
restaurants_raw_tripadvisor
   -> [tripadvisor-clean]
restaurants_clean_tripadvisor
```

The work is:

1. Add rich-field parsing and slim projection for fields currently passed through raw.
2. Add per-record quality flags and report counters comparable to Google/TheFork.
3. Add full-run stale-delete convergence and a source/destination collision guard.
4. Add a small deletion/drop-policy document for Tripadvisor before introducing any
   default drop rules.
5. Bring Tripadvisor docs and project READMEs to the same standard as Google and
   TheFork.
6. Drop empty/dead fields from the cleaned collection where they add no analytical value.

Rating-scale harmonization is explicitly out of scope for this feature.

## Functional Requirements

### A. Rich field parsing

- Parse `number_photo_uploaded` into `photo_count: int | null`.
  - Accept Italian thousands separators if they appear.
  - `NaN`, blank, missing, or unparseable values become `null`.
  - Do not keep `number_photo_uploaded` in the clean document.
- Parse `price_range` into structured price fields.
  - Preserve an interpretable source-specific price tier, for example
    `price_band_raw` or `price_tier`, and a normalized ordinal such as
    `price_tier_level`.
  - Expected raw values include `EUR`, `EUR-EUR`, and luxury bands rendered with euro
    symbols; implementation should handle the current exact strings without assuming
    free text.
  - Do not keep the original raw `price_range` unless the final design uses a clearly
    named raw/audit field; the immutable raw collection is the main audit trail.
- Split `cuisine_type` into `cuisines: list[str]`.
  - Trim tokens, remove empty tokens, preserve source vocabulary and original language.
  - De-duplicate case-insensitively while preserving first-seen order.
  - Missing/`NaN` becomes `[]`.
  - Track `cuisines_present` and `multi_cuisine` in `CleanReport`.
- Parse `working_days_hours` into `opening_hours: list[dict]`.
  - The parser should be conservative: emit a tidy structure only when day/time
    segments are confidently parsed.
  - Preserve split shifts where available.
  - Missing/malformed values become `[]`, not `null`.
  - Add `has_hours: bool`.
- Slim `review` into `reviews: list[dict]`.
  - Keep only analytically useful fields: author nickname, author contribution count
    when parseable, title, text, and publication date.
  - Remove display artifacts from review text, including the repeated read-more suffix.
  - `review == "NaN"` becomes `reviews = []`.
  - Add `has_reviews: bool` and `sample_size`.
- Keep `ta_location_id` extraction as-is and treat it as the stable Tripadvisor venue id
  for downstream blocking.

### B. Quality flags

- Add per-record boolean fields:
  - `has_rating`
  - `has_review_count`
  - `low_review`
  - `has_address`
  - `has_coordinates`
  - `has_reviews`
  - `has_hours`
  - `has_phone`
  - `has_website`
  - `has_email`
- Add `flags: list[str]`, following the style used by Google and TheFork.
  - Candidate reasons: `no_rating`, `missing_review_count`, `low_review`,
    `missing_address`, `geocode_not_found`, `missing_coordinates`,
    `rating_with_zero_reviews`, `no_reviews`, `no_hours`.
  - Keep the list empty when no flags apply.
- `low_review` is count-only and must not delete records.
  - Default threshold remains 10 unless a later decision changes the shared threshold.
  - Missing review count is not the same as low review count.
- Add `CleanReport` counters for the new flags and parsed fields.
  - Include at least: `photo_count_parsed`, `price_parsed`, `cuisines_present`,
    `multi_cuisine`, `opening_hours_parsed`, `with_reviews`, `with_phone`,
    `with_website`, `with_email`, `with_rating`, `without_rating`,
    `missing_review_count`, `rating_with_zero_reviews`, and `stale_deleted`.

### C. Rerun convergence and deletion behavior

- Add the same `source_collection != destination_collection` guard used by
  `google_clean` and `thefork_clean`.
  - If source and destination are equal, raise a clear `ValueError` before reading or
    writing data.
- Add full-run stale-delete convergence.
  - On a full run (`limit is None`), delete destination documents whose `_id` was not
    seen in the current source collection.
  - On a limited run (`--limit`), never delete unread destination records.
  - Report the number as `stale_deleted`.
- Preserve Tripadvisor geocoding resumability.
  - Existing coordinates must still be preserved/skipped where both latitude and
    longitude are already present.
  - `--skip-geocode` must still update deterministic clean fields while preserving
    existing coordinates.
- Create a documented Tripadvisor drop/deletion policy before adding any default drop
  rules.
  - Suggested file: `services/transform/tripadvisor_clean/drop-policy.md`.
  - The document should answer whether any records are bad enough to exclude from the
    clean collection by default.
  - It should include concrete criteria, for example missing key, missing name, missing
    address, no rating plus no reviews, geocode failure, or other unusable combinations.
  - Initial implementation should be flag-first unless the policy justifies a narrow
    default drop class.

### D. Clean schema hygiene

- Drop fields from clean Tripadvisor documents when they are raw-only, empty, or replaced
  by parsed fields.
  - Replace `number_photo_uploaded` with `photo_count`.
  - Replace `cuisine_type` with `cuisines`.
  - Replace `working_days_hours` with `opening_hours`.
  - Replace `review` with `reviews`.
  - Replace or structure `price_range` as described above.
- Keep contact fields only if they carry value in the raw data.
  - Tripadvisor currently has non-empty `website`, `phone_number`, and `email`, so they
    should remain, but normalized and paired with `has_*` booleans.
  - Empty strings and `"NaN"` must become `null`.
- Keep raw collection as the audit trail.
  - Do not add broad `*_raw` shadows unless a field has no clean representation and is
    needed directly by downstream logic.

### E. Documentation parity

- Add a strict Tripadvisor EDA / data-quality report comparable to:
  - `services/extract/google_places_api/eda-report.md`
  - `services/extract/thefork_scraper/eda-report.md`
- Add a clean dataset schema for Tripadvisor comparable to:
  - `services/transform/google_clean/clean-dataset-schema.md`
  - The TheFork transform README/schema-level documentation.
- Update `services/transform/tripadvisor_clean/README.md`.
  - Document rich parsed fields, flags, stale-delete behavior, drop policy, and
    clean schema.
- Update `services/README.md`.
  - List all three transform services, not just Tripadvisor.
  - Include `google-clean`, `tripadvisor-clean`, and `thefork-clean` examples.
- Update the root project README if it omits implemented transforms or still describes
  stale pipeline state.
- Update `docs/PIPELINE.md` if it omits `thefork_clean` or describes transforms as
  incomplete.
- Keep docs explicit that raw data remains immutable and that clean collections are
  reproducible products of Mongo -> Mongo transforms.

## Possible Edge Cases

- `number_photo_uploaded` may be `"NaN"`, blank, a simple integer string, or a value with
  thousands separators.
- `price_range` values may render as euro symbols and separators; parsing should not
  mistake an unknown string for a valid tier.
- `cuisine_type` may be missing, a single token, repeated tokens, or a comma-separated
  list with extra whitespace.
- `working_days_hours` may include closed days, split shifts, malformed segments, or
  source language day names.
- `review` may be `"NaN"`, an empty list, or a list with partial author metadata.
- Review text may contain display artifacts that should be removed without damaging real
  review text.
- `rating` can be present while `total_review == 0`; this should be flagged, not
  dropped.
- `rating` can be missing while `total_review` is present; this should be flagged, not
  backfilled from review samples.
- Geocoding can fail for records with valid addresses; those records should remain
  flagged unless the drop-policy document later decides otherwise.
- A full run after upstream source shrinkage must remove stale clean docs.
- A limited run must never delete records it did not read.
- Source and destination collection names can collide through shared `DATAMAN_`
  environment variables.

## Acceptance Criteria

- `tripadvisor-clean` still reads `restaurants_raw_tripadvisor` and writes
  `restaurants_clean_tripadvisor`, keyed on `source_url`.
- Clean documents contain parsed rich fields:
  - `photo_count`
  - structured price fields
  - `cuisines`
  - `opening_hours`
  - `reviews`
  - `has_*` booleans and `flags`
- Clean documents no longer carry replaced raw fields:
  - `number_photo_uploaded`
  - `price_range` unless intentionally renamed as a clean raw/tier field
  - `cuisine_type`
  - `working_days_hours`
  - `review`
- `CleanReport` includes parsed-field coverage, quality-flag counts, and
  `stale_deleted`.
- A full rerun deletes destination docs whose keys disappeared from the source.
- A limited rerun does not delete unread destination docs.
- Source/destination collection collision raises a clear error before mutation.
- Existing geocoding behavior still works:
  - resumability skips already geocoded records;
  - partial coordinates are re-geocoded;
  - `--skip-geocode` preserves existing coordinates.
- A Tripadvisor drop-policy document exists and explains whether any default clean-layer
  exclusions are justified.
- Tripadvisor has strict EDA and clean-schema documentation comparable to Google and
  TheFork.
- `services/README.md`, root README if needed, and `docs/PIPELINE.md` reflect all three
  implemented transforms.

## Open Questions

- What exact normalized price schema should Tripadvisor use: `price_tier_level`,
  `price_band`, both, or another name?
- Should `opening_hours` preserve the original Italian day names alongside canonical
  English day names?
- Should the clean review object keep review title, or should title be dropped if it is
  mostly display noise?
- Should the drop policy ever exclude records from the clean collection, or should
  Tripadvisor stay entirely flag-first except for missing natural keys?

## Out of Scope

- Cross-source rating-scale harmonization.
- Entity resolution and unified dataset construction.
- ClickHouse analytics table work.
- Re-geocoding Google or TheFork.
- Changing scraper extraction logic for Tripadvisor.
- Translating cuisine names or reviews.
- Backfilling missing Tripadvisor ratings from review samples.

## Feature Testing Guidelines

Create tests under `tests/transform/tripadvisor_clean/` without going too heavy:

- Pure cleaner tests:
  - photo-count parsing;
  - price-tier parsing;
  - cuisine splitting and de-duplication;
  - opening-hours parsing for normal, split-shift, missing, and malformed values;
  - review slimming and read-more artifact cleanup;
  - flag derivation.
- Transform orchestration tests with `mongomock`:
  - clean rich fields are written and replaced raw fields are absent;
  - full-run stale-delete behavior;
  - limited-run no-delete behavior;
  - source/destination collision guard;
  - report counters for rich fields and flags.
- Existing geocoding tests should continue to cover:
  - geocode found/not found;
  - skip null address;
  - skip already geocoded;
  - partial coordinates get re-geocoded;
  - `--skip-geocode` preserves coordinates.
