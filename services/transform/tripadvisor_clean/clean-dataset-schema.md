# Clean Dataset Schema - `restaurants_clean_tripadvisor`

Output of the `tripadvisor_clean` transform (`uv run tripadvisor-clean`), Mongo -> Mongo.
The raw input is `restaurants_raw_tripadvisor`; the clean output is one document per
Tripadvisor venue in `restaurants_clean_tripadvisor`, keyed by `source_url` (`_id`).

Coverage figures are from a deterministic pass over **7,539 raw records**. Coordinate
coverage is geocoding-dependent: a `--skip-geocode` run leaves coordinates null, while a
full run attempts Nominatim/OpenStreetMap geocoding on the cleaned address.

## Old Features - Raw Source Schema

| Field | Type | Coverage | Description |
|---|---|---:|---|
| `source_url` | str | 100% | Tripadvisor restaurant URL and natural key. |
| `restaurant_name` | str | 100% | Raw display name from the Tripadvisor page. |
| `rating` | str | 99.8% | Aggregate rating as an Italian display string, for example `4,5`. |
| `total_review` | str | 100% | Review count as page text, for example `(1.234 recensioni)`. |
| `cuisine_type` | str | 77.7% | Comma-separated cuisine labels or `NaN`. |
| `price_range` | str | 67.7% | Price band rendered with one, two-to-three, or four euro symbols, or `NaN`. |
| `number_photo_uploaded` | str | 78.9% | Photo count as a string or `NaN`. |
| `address` | str | 99.1% | Full free-text address line or `NaN`. Tripadvisor does not provide coordinates. |
| `website` | str | 79.9% | Venue website URL or `NaN`. |
| `phone_number` | str | 90.1% | Phone number as displayed or `NaN`. |
| `email` | str | 46.9% | Contact email or `NaN`. |
| `working_days_hours` | str | 67.6% | Flattened opening-hours text in Italian. |
| `review` | list[obj] \| str | 88.6% | First-page review list, or literal `NaN` when absent. |
| `review[].author.nickname` | str | about 100% of reviews | Raw reviewer nickname. |
| `review[].author.number_of_contribution` | str | varies | Contribution count as rendered text. |
| `review[].title` | str | about 100% of reviews | Raw review headline. |
| `review[].text` | str | about 100% of reviews | Raw review body, sometimes ending with the page expander text. |
| `review[].date_of_publication` | str | about 100% of reviews | Italian date string, for example `16 maggio 2026`. |

## New Features - Clean Schema

| Field | Type | Coverage | Transformed | Description |
|---|---|---:|---|---|
| `_id` | str | 100% | Created from `source_url`. | Mongo key for idempotent upserts. |
| `source_url` | str | 100% | Copied from raw `source_url`. | Tripadvisor natural key. |
| `ta_location_id` | str \| null | 100% | Extracted from the `-d<n>-` token in `source_url`. | Stable Tripadvisor venue id for blocking and audit. |
| `restaurant_name` | str \| null | 100% | Whitespace collapsed from raw `restaurant_name`. | Clean display name. |
| `latitude` | float \| null | geocode-dependent | Geocoded from the cleaned `address` with Nominatim/OpenStreetMap. | Estimated latitude because Tripadvisor has no native coordinates. |
| `longitude` | float \| null | geocode-dependent | Geocoded from the cleaned `address` with Nominatim/OpenStreetMap. | Estimated longitude because Tripadvisor has no native coordinates. |
| `has_coordinates` | bool | 100% | Derived after geocoding from both coordinates being present. | Coordinate coverage flag. |
| `address` | str \| null | 99.1% | `NaN`/blank to null; whitespace and separators normalized. | Clean full address line. |
| `street` | str \| null | 99.1% | Parsed from the normalized `address` before the postal code. | Street/address prefix for matching. |
| `postal_code` | str \| null | 95.9% | Extracted as a 5-digit Italian CAP from `address`. | Postal code for blocking and consistency checks. |
| `city` | str \| null | 95.9% | Parsed from `address` after the postal code, with country stripped. | City string for blocking and consistency checks. |
| `has_address` | bool | 100% | Derived from `address is not null`. | Address coverage flag. |
| `rating` | float \| null | 99.8% | Parsed from raw comma-decimal `rating`; invalid/out-of-range to null. | Tripadvisor aggregate rating on a 1-5 scale. |
| `total_review` | int \| null | 100% | Parsed from raw parenthesized Italian review-count text. | Tripadvisor review count. |
| `has_rating` | bool | 100% | Derived from `rating is not null`. | Rating coverage flag. |
| `has_review_count` | bool | 100% | Derived from `total_review is not null`. | Review-count coverage flag. |
| `low_review` | bool | 100% | Derived from `total_review < low_review_threshold` when count exists. | Count-only quality flag; records are kept. |
| `photo_count` | int \| null | 78.9% | Parsed from `number_photo_uploaded`; `NaN` to null. | Uploaded-photo count. |
| `price_band` | str \| null | 67.7% | Validated and cleaned from raw `price_range`. | Source euro-symbol price band. |
| `price_tier_level` | int \| null | 67.7% | Derived from the lower bound of `price_band`. | Ordinal price tier. |
| `cuisines` | list[str] | 77.7% non-empty | Split from comma-separated `cuisine_type`; trimmed and de-duplicated case-insensitively. | Source cuisine vocabulary for faceting/matching. |
| `opening_hours` | list[obj] | 67.6% non-empty | Parsed from `working_days_hours`; Italian day names mapped to canonical English; split shifts preserved. | Tidy hours as `{day, opens, closes}` objects. |
| `reviews` | list[obj] | 88.6% non-empty | Slimmed from raw `review` to capped `{nickname, contributions, title, text, date}` objects. | Recent first-page review sample. |
| `sample_size` | int | 100% | Derived as `len(reviews)`. | Number of retained sample reviews; not the same as `total_review`. |
| `has_reviews` | bool | 100% | Derived from `reviews` being non-empty. | Review-sample coverage flag. |
| `has_hours` | bool | 100% | Derived from `opening_hours` being non-empty. | Opening-hours coverage flag. |
| `website` | str \| null | 79.9% | `NaN`/blank to null; whitespace trimmed. | Venue website used as matching evidence. |
| `phone_number` | str \| null | 90.1% | `NaN`/blank to null; whitespace trimmed. | Phone number used as matching evidence. |
| `email` | str \| null | 46.9% | `NaN`/blank to null; whitespace trimmed. | Contact email for audit/enrichment. |
| `has_website` | bool | 100% | Derived from `website is not null`. | Website coverage flag. |
| `has_phone` | bool | 100% | Derived from `phone_number is not null`. | Phone coverage flag. |
| `has_email` | bool | 100% | Derived from `email is not null`. | Email coverage flag. |
| `flags` | list[str] | 100% | Derived reason list from quality checks and geocoding outcome. | May include `no_rating`, `missing_review_count`, `low_review`, `missing_address`, `geocode_not_found`, `missing_coordinates`, `rating_with_zero_reviews`, `no_reviews`, `no_hours`. |
| `_transformed_at` | datetime | 100% | Added by transform at write time. | UTC transform timestamp. |
| `_source_collection` | str | 100% | Added from transform settings. | Source collection name, normally `restaurants_raw_tripadvisor`. |
