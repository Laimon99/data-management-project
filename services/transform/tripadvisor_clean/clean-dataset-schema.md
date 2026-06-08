# Clean Dataset Schema - `restaurants_clean_tripadvisor`

Output of the `tripadvisor_clean` transform (`uv run tripadvisor-clean`), Mongo -> Mongo.
The tables below describe fields in the clean output, not the full raw input. Fields
that are copied unchanged from raw appear only in the first table. Fields that are
parsed, normalized, geocoded, derived, or created by the transform appear only in the
second table.

Coverage figures match the current Mongo audit of **7,539 clean documents**. This
collection was last produced with `uv run tripadvisor-clean --skip-geocode`, so the
coordinate fields exist with the correct names (`latitude`, `longitude`) but currently
have **0% non-null coverage**. A full geocoding run would change only coordinate coverage
and coordinate-derived flags.

Raw-only inputs such as `number_photo_uploaded`, `price_range`, `cuisine_type`,
`working_days_hours`, and `review` are replaced by clean fields and remain in
`restaurants_raw_tripadvisor` as the audit trail.

## Schema Overview

| Semantic group | Fields |
|---|---|
| Identity | `_id`, `source_url`, `ta_location_id`, `restaurant_name` |
| Coordinates | `latitude`, `longitude`, `has_coordinates` |
| Address | `address`, `street`, `house_number`, `postal_code`, `city`, `has_address` |
| Ratings | `rating`, `total_review`, `has_rating`, `has_review_count`, `low_review` |
| Price and cuisine | `price_band`, `price_tier_level`, `cuisines` |
| Source richness | `photo_count`, `opening_hours`, `has_hours` |
| Review sample | `reviews`, `sample_size`, `has_reviews` |
| Contacts | `website`, `phone`, `email`, `has_website`, `has_phone`, `has_email` |
| Quality flags | `flags` |
| Transform metadata | `_transformed_at`, `_source_collection` |

## Old Features - Kept Unchanged

| Field | Type | Coverage | Description |
|---|---|---:|---|
| `source_url` | str | 100% | Tripadvisor restaurant URL and natural key, copied unchanged. |

## New Or Transformed Features

| Field | Type | Coverage | Transformed | Description |
|---|---|---:|---|---|
| `_id` | str | 100% | Created from `source_url`. | Mongo key for idempotent upserts. |
| `ta_location_id` | str \| null | 100% | Extracted from the `-d<n>-` token in `source_url`. | Stable Tripadvisor venue id for blocking and audit. |
| `restaurant_name` | str \| null | 100% | Normalized from raw `restaurant_name`: whitespace collapsed. | Clean display name. |
| `latitude` | float \| null | 0% | Created by geocoding the cleaned `address`; current Mongo collection was run with `--skip-geocode`, so all values are null. | Estimated latitude field because Tripadvisor has no native coordinates. |
| `longitude` | float \| null | 0% | Created by geocoding the cleaned `address`; current Mongo collection was run with `--skip-geocode`, so all values are null. | Estimated longitude field because Tripadvisor has no native coordinates. |
| `has_coordinates` | bool | 100% | Created from both `latitude` and `longitude` being present; false for the current skip-geocode collection. | Coordinate coverage flag. |
| `address` | str \| null | 99.1% | Normalized from raw `address`: `NaN`/blank to null; whitespace and separators normalized. | Clean full address line. |
| `street` | str \| null | 99.1% | Parsed from the normalized `address` before the first digit-starting civic-number token. | Route/street name for matching. |
| `house_number` | str \| null | TBD after rerun | Parsed as the first digit-starting token after the route/street name. | Civic number for address matching. |
| `postal_code` | str \| null | 95.9% | Extracted as a 5-digit Italian CAP from `address`. | Postal code for blocking and consistency checks. |
| `city` | str \| null | 95.9% | Parsed from `address` after the postal code, with country stripped. | City string for blocking and consistency checks. |
| `has_address` | bool | 100% | Created from `address is not null`. | Address coverage flag. |
| `rating` | float \| null | 99.8% | Parsed from raw comma-decimal `rating`; invalid/out-of-range to null. | Tripadvisor aggregate rating on a 1-5 scale. |
| `total_review` | int \| null | 100% | Parsed from raw parenthesized Italian review-count text. | Tripadvisor review count. |
| `has_rating` | bool | 100% | Created from `rating is not null`. | Rating coverage flag. |
| `has_review_count` | bool | 100% | Created from `total_review is not null`. | Review-count coverage flag. |
| `low_review` | bool | 100% | Created from `total_review < low_review_threshold` when count exists. | Count-only quality flag; records are kept. |
| `photo_count` | int \| null | 78.9% | Parsed from raw `number_photo_uploaded`; `NaN` to null. | Uploaded-photo count. |
| `price_band` | str \| null | 67.7% | Parsed and validated from raw `price_range`. | Source euro-symbol price band. |
| `price_tier_level` | int \| null | 67.7% | Created from the lower bound of `price_band`. | Ordinal price tier. |
| `cuisines` | list[str] | 77.7% non-empty | Split from raw comma-separated `cuisine_type`; trimmed and de-duplicated case-insensitively. | Source cuisine vocabulary for faceting/matching. |
| `opening_hours` | list[obj] | 67.6% non-empty | Parsed from raw `working_days_hours`; Italian day names mapped to canonical English; split shifts preserved. | Tidy hours as `{day, opens, closes}` objects. |
| `reviews` | list[obj] | 88.6% non-empty | Slimmed from raw `review` to capped `{nickname, contributions, title, text, date}` objects. | Recent first-page review sample. |
| `sample_size` | int | 100% | Created as `len(reviews)`. | Number of retained sample reviews; not the same as `total_review`. |
| `has_reviews` | bool | 100% | Created from `reviews` being non-empty. | Review-sample coverage flag. |
| `has_hours` | bool | 100% | Created from `opening_hours` being non-empty. | Opening-hours coverage flag. |
| `website` | str \| null | 79.9% | Normalized from raw `website`: `NaN`/blank to null; scheme, leading `www.`, and trailing `/` stripped. | Normalized venue website used as matching evidence. |
| `phone` | str \| null | 90.1% | Normalized from raw `phone_number`: `NaN`/blank to null; formatting stripped; Italian national numbers get `+39`. | Normalized phone number used as matching evidence. |
| `email` | str \| null | 46.9% | Normalized from raw `email`: `NaN`/blank to null; whitespace trimmed. | Contact email for audit/enrichment. |
| `has_website` | bool | 100% | Created from `website is not null`. | Website coverage flag. |
| `has_phone` | bool | 100% | Created from `phone is not null`. | Phone coverage flag. |
| `has_email` | bool | 100% | Created from `email is not null`. | Email coverage flag. |
| `flags` | list[str] | 100% | Created as a reason list from quality checks and geocoding outcome. | May include `no_rating`, `missing_review_count`, `low_review`, `missing_address`, `geocode_not_found`, `missing_coordinates`, `rating_with_zero_reviews`, `no_reviews`, `no_hours`. |
| `_transformed_at` | datetime | 100% | Added by transform at write time. | UTC transform timestamp. |
| `_source_collection` | str | 100% | Added from transform settings. | Source collection name, normally `restaurants_raw_tripadvisor`. |

## Deleted Or Replaced Raw Fields

| Raw Field | Type | Coverage | Deleted / Replaced By | Reason |
|---|---|---:|---|---|
| `number_photo_uploaded` | str | 78.9% | `photo_count` | Replaced by parsed integer photo count. |
| `price_range` | str | 67.7% | `price_band`, `price_tier_level` | Replaced by validated price band and derived ordinal tier. |
| `cuisine_type` | str | 77.7% | `cuisines` | Replaced by a trimmed/de-duplicated cuisine list. |
| `working_days_hours` | str | 67.6% | `opening_hours` | Replaced by structured opening-hours objects. |
| `review` | list[obj] \| str | 88.6% | `reviews`, `sample_size`, `has_reviews` | Replaced by capped slim review objects and sample features. |
| `phone_number` | str \| null | 90.1% | `phone` | Replaced by canonical normalized clean phone; original source value remains in raw. |
