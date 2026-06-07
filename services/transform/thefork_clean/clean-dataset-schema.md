# Clean Dataset Schema - `restaurants_clean_thefork`

Output of the `thefork_clean` transform (`uv run thefork-clean`), Mongo -> Mongo. The
tables below describe fields in the clean output, not the full raw input. Fields that
are copied unchanged from raw appear only in the first table. Fields that are normalized,
validated, parsed, derived, or created by the transform appear only in the second table.

Coverage figures match the current Mongo audit of **1,344 clean documents** in
`restaurants_clean_thefork`. TheFork ratings remain on the native **0-10** scale;
rating-scale harmonization is deferred to the integrated dataset.

Raw-only inputs such as `price_range`, `discount`, `cuisine_type`, `working_days_hours`,
`phone_number`, `email`, and review titles are either replaced by clean fields or
dropped, while the full raw collection remains the audit trail.

## Schema Overview

| Semantic group | Fields |
|---|---|
| Identity | `_id`, `source`, `source_id`, `tf_id`, `restaurant_url`, `restaurant_name` |
| Coordinates | `latitude`, `longitude` |
| Address | `address`, `street`, `house_number`, `postal_code`, `city` |
| Ratings | `rating`, `review_count`, `has_rating`, `has_review_count`, `low_review` |
| Price and promotions | `avg_price_eur`, `discount_pct`, `has_discount` |
| Cuisine | `cuisines`, `dietary_options` |
| Opening hours | `opening_hours`, `has_hours` |
| Source richness | `photo_count`, `review_snippets` |
| Review sample | `reviews`, `sample_size`, `sample_avg_rating`, `rating_sample_divergent`, `has_reviews` |
| Scrape provenance | `scraped_at`, `source_page_number`, `detail_scraped` |
| Quality flags | `flags` |
| Transform metadata | `_transformed_at`, `_source_collection` |

## Old Features - Kept Unchanged

| Field | Type | Coverage | Description |
|---|---|---:|---|
| `source` | str | 100% | Constant source label, copied unchanged. |
| `source_id` | str | 100% | TheFork slug plus stable `-r<n>` venue id, copied unchanged as the natural key. |
| `restaurant_url` | str | 100% | TheFork restaurant detail URL, copied unchanged. |
| `latitude` | float \| null | 99.8% | TheFork latitude, copied unchanged and never re-geocoded. |
| `longitude` | float \| null | 99.8% | TheFork longitude, copied unchanged and never re-geocoded. |
| `photo_count` | int \| null | 99.7% | TheFork photo count, copied unchanged. |
| `review_snippets` | list[str] | 96.1% non-empty | Short review snippets, copied unchanged. |
| `scraped_at` | str | 100% | Source scrape timestamp, copied unchanged. |
| `source_page_number` | int | 100% | Listing page number, copied unchanged. |
| `detail_scraped` | bool | 100% | Detail-enrichment provenance flag, copied unchanged. |

## New Or Transformed Features

| Field | Type | Coverage | Transformed | Description |
|---|---|---:|---|---|
| `_id` | str | 100% | Created from `source_id`. | Mongo key for idempotent upserts. |
| `tf_id` | str \| null | 100% | Extracted from the trailing `-r<n>` token in `source_id`. | Stable TheFork venue id for blocking and audit. |
| `restaurant_name` | str \| null | 100% | Normalized from raw `restaurant_name`: whitespace collapsed, ALL-CAPS recased best-effort. | Clean display name. |
| `address` | str \| null | 100% | Normalized from raw `address`: whitespace/commas normalized, `I-` CAP prefix stripped, English `Milan`/`Italy` folded to `Milano`/`Italia`. | Clean full address string. |
| `street` | str \| null | 100% | Parsed from the first comma-separated address chunk. | Street name. |
| `house_number` | str \| null | 96.4% | Parsed from the second address chunk when it starts with a digit. | Civic number. |
| `postal_code` | str \| null | 99.8% | Extracted as a 5-digit CAP from normalized `address`. | Postal code for blocking and consistency checks. |
| `city` | str \| null | 100% | Canonicalized from raw `city`: `Milan` to `Milano`. | Canonical city string. |
| `rating` | float \| null | 96.7% | Validated from raw `rating`; only numeric values inside 0-10 are kept. | TheFork native aggregate rating. |
| `review_count` | int \| null | 97.0% | Validated from raw `review_count`; only non-negative integers are kept. | TheFork review count. |
| `has_rating` | bool | 100% | Created from `rating is not null`. | Rating coverage flag. |
| `has_review_count` | bool | 100% | Created from `review_count is not null`. | Review-count coverage flag. |
| `low_review` | bool | 100% | Created from `review_count < low_review_threshold` when count exists. | Count-only quality flag; records are kept. |
| `avg_price_eur` | int \| null | 100% | Parsed from raw `price_range` by extracting the integer amount. | Average price in EUR. |
| `discount_pct` | int \| null | 69.4% | Parsed from raw `discount` only when it is clean promo text; noisy/multi-percent text becomes null. | Discount percentage when a valid promotion is present. |
| `has_discount` | bool | 100% | Created from raw `discount` being non-empty, independent of parse success. | Promotion coverage flag. |
| `cuisines` | list[str] | 98.1% non-empty | Split from raw `cuisine_type`; trimmed; de-duplicated; address leaks rejected. | Source cuisine vocabulary. |
| `dietary_options` | list[str] | 37.8% non-empty | Created by lifting dietary/religious tokens from raw `cuisine_type` and mapping to canonical English tags. | Tags such as `vegetarian`, `vegan`, `gluten_free`, `organic`, `halal`, `kosher`. |
| `opening_hours` | list[obj] | 63.5% non-empty | Created from structured hours when present, otherwise parsed from `working_days_hours`; day names normalized; past-midnight times folded. | Tidy hours as `{day, opens, closes}` objects, with `closes_next_day` when needed. |
| `has_hours` | bool | 100% | Created from `opening_hours` being non-empty. | Opening-hours coverage flag. |
| `reviews` | list[obj] | 95.2% non-empty | Slimmed from raw `reviews` to capped `{author_name, rating, text, date}` objects; null `title` dropped. | Recent review sample, not the full review population. |
| `sample_size` | int | 100% | Created as `len(reviews)`. | Number of retained nested reviews. |
| `sample_avg_rating` | float \| null | 95.2% | Created as the mean of numeric ratings inside the retained review sample. | Sample-only quality signal; never used to backfill platform rating. |
| `rating_sample_divergent` | bool | 100% | Created when `abs(rating - sample_avg_rating) > 1.0`. | Flags disagreement between platform rating and recent sample average. |
| `has_reviews` | bool | 100% | Created from `reviews` being non-empty. | Review-sample coverage flag. |
| `flags` | list[str] | 19.3% non-empty | Created as a reason list from quality checks; field is present on every document. | May include `no_rating`, `missing_review_count`, `low_review`, `rating_sample_divergent`, `invalid_cuisine_type`; empty list when no flags apply. |
| `_transformed_at` | datetime | 100% | Added by transform at write time. | UTC transform timestamp. |
| `_source_collection` | str | 100% | Added from transform settings. | Source collection name, normally `restaurants_raw_thefork`. |

## Deleted Or Replaced Raw Fields

| Raw Field | Type | Coverage | Deleted / Replaced By | Reason |
|---|---|---:|---|---|
| `price_range` | str | 100% | `avg_price_eur` | Replaced by numeric EUR average price. |
| `discount` | str \| null | 70.6% | `discount_pct`, `has_discount` | Replaced by parsed promotion percentage plus presence flag. |
| `cuisine_type` | str \| null | 98.4% | `cuisines`, `dietary_options` | Replaced by cuisine and dietary-option lists. |
| `working_days_hours` | str \| null | 63.5% | `opening_hours` | Replaced by tidy opening-hours objects. |
| `phone_number` | str \| null | 0% | deleted | Empty in the current scrape; kept only in raw audit data. |
| `email` | str \| null | 0% | deleted | Empty in the current scrape; kept only in raw audit data. |
| `reviews[].title` | null | 0% | deleted from `reviews` | Always null in nested reviews, so slim review objects omit it. |
