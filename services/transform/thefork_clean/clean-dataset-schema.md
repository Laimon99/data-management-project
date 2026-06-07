# Clean Dataset Schema - `restaurants_clean_thefork`

Output of the `thefork_clean` transform (`uv run thefork-clean`), Mongo -> Mongo. The
raw input is `restaurants_raw_thefork`; the clean output is one lean document per
TheFork venue in `restaurants_clean_thefork`, keyed by `source_id` (`_id`).

Coverage figures use the current TheFork raw file
`data/raw/thefork/thefork_milan_restaurants_enriched.json`, **1,344 records**, scraped on
2026-06-06. "Coverage" means non-null coverage unless the description says "non-empty"
for arrays. TheFork ratings remain on the native **0-10** scale; rating-scale
harmonization is deferred to the integrated dataset.

## Old Features - Raw Source Schema

| Field | Type | Coverage | Description |
|---|---|---:|---|
| `source` | str | 100% | Constant source label, `thefork`. |
| `source_id` | str | 100% | TheFork slug plus stable `-r<n>` venue id; raw natural key. |
| `restaurant_name` | str | 100% | Raw venue display name. |
| `address` | str | 100% | Composite full address string. |
| `city` | str | 100% | Raw city string, currently English `Milan`. |
| `latitude` | float | 100% | TheFork-provided latitude. |
| `longitude` | float | 100% | TheFork-provided longitude. |
| `rating` | float \| null | 94.1% | TheFork aggregate rating on a 0-10 scale. |
| `review_count` | int \| null | 98.1% | TheFork review count. |
| `cuisine_type` | str \| null | 98.4% | Cuisine display text, usually atomic in the current scrape but treated as comma-separated. |
| `price_range` | str | 100% | Average price display string, for example `30 EUR` in source text form. |
| `discount` | str \| null | 48.4% | Promotion text containing a percentage when a discount is shown. |
| `photo_count` | int \| null | 99.9% | TheFork photo count. |
| `website` | str \| null | 0% | Empty in the current scrape; dropped from clean output. |
| `social_links` | obj | 0% non-empty | Present but empty for every record; dropped from clean output. |
| `phone_number` | str \| null | 0% | Empty in the current scrape; dropped from clean output. |
| `email` | str \| null | 0% | Empty in the current scrape; dropped from clean output. |
| `working_days_hours` | str \| null | 63.6% | Raw serialized opening-hours JSON string. |
| `working_hours_structured` | list[obj] | 63.6% non-empty | Pre-parsed schema.org opening-hours objects from the newer scraper. |
| `restaurant_url` | str | 100% | TheFork restaurant detail URL. |
| `review_snippets` | list[str] | 96.7% non-empty | Short review snippets. |
| `reviews` | list[obj] | 96.7% non-empty | Nested review sample, capped at 15 in the current scrape. |
| `reviews[].title` | null | 0% | Always null in the nested reviews; dropped from clean review objects. |
| `scraped_at` | str | 100% | Scrape timestamp. |
| `source_page_number` | int | 100% | Listing page number where the venue was found. |
| `detail_scraped` | bool | 100% | Detail-enrichment completion flag. |

## New Features - Clean Schema

| Field | Type | Coverage | Transformed | Description |
|---|---|---:|---|---|
| `_id` | str | 100% | Created from `source_id`. | Mongo key for idempotent upserts. |
| `source` | str | 100% | Copied from raw `source`. | Source label. |
| `source_id` | str | 100% | Copied from raw `source_id`. | TheFork natural key. |
| `tf_id` | str \| null | 100% | Extracted from the trailing `-r<n>` token in `source_id`. | Stable TheFork venue id for blocking and audit. |
| `restaurant_url` | str | 100% | Copied from raw `restaurant_url`. | Source detail URL. |
| `restaurant_name` | str \| null | 100% | Whitespace collapsed; ALL-CAPS names recased best-effort. | Clean display name. |
| `latitude` | float | 100% | Copied from raw `latitude`; never re-geocoded. | TheFork latitude. |
| `longitude` | float | 100% | Copied from raw `longitude`; never re-geocoded. | TheFork longitude. |
| `address` | str \| null | 100% | Whitespace/commas normalized; `I-` CAP prefix stripped; English `Milan`/`Italy` folded to `Milano`/`Italia`. | Clean full address string. |
| `street` | str \| null | 100% | Parsed from the first comma-separated address chunk. | Street name. |
| `house_number` | str \| null | 96.4% | Parsed from the second address chunk when it starts with a digit. | Civic number. |
| `postal_code` | str \| null | 100% | Extracted as a 5-digit CAP from normalized `address`. | Postal code for blocking and consistency checks. |
| `city` | str \| null | 100% | Raw `city` canonicalized from `Milan` to `Milano`. | Canonical city string. |
| `rating` | float \| null | 94.1% | Passed through only when numeric and inside 0-10. | TheFork native aggregate rating. |
| `review_count` | int \| null | 98.1% | Passed through only when a non-negative integer. | TheFork review count. |
| `has_rating` | bool | 100% | Derived from `rating is not null`. | Rating coverage flag. |
| `has_review_count` | bool | 100% | Derived from `review_count is not null`. | Review-count coverage flag. |
| `low_review` | bool | 100% | Derived from `review_count < low_review_threshold` when count exists. | Count-only quality flag; records are kept. |
| `avg_price_eur` | int \| null | 100% | Parsed from raw `price_range` by extracting the integer amount. | Average price in EUR. |
| `discount_pct` | int \| null | 48.4% | Parsed from clean discount text only; noisy/multi-percent text becomes null. | Discount percentage when a valid promotion is present. |
| `has_discount` | bool | 100% | Derived from raw `discount` being non-empty, independent of parse success. | Promotion coverage flag. |
| `cuisines` | list[str] | 98.1% non-empty | Split from `cuisine_type`; trimmed; de-duplicated; address leaks rejected. | Source cuisine vocabulary. |
| `dietary_options` | list[str] | 0.2% non-empty | Dietary/religious tokens lifted from `cuisine_type` and mapped to canonical English tags. | Tags such as `vegetarian`, `vegan`, `gluten_free`, `organic`, `halal`, `kosher`. |
| `opening_hours` | list[obj] | 63.6% non-empty | Prefer `working_hours_structured`; fallback to JSON parsing `working_days_hours`; day names normalized to English; past-midnight times folded. | Tidy hours as `{day, opens, closes}` objects, with `closes_next_day` when needed. |
| `has_hours` | bool | 100% | Derived from `opening_hours` being non-empty. | Opening-hours coverage flag. |
| `photo_count` | int \| null | 99.9% | Copied from raw `photo_count` when present. | TheFork photo count. |
| `reviews` | list[obj] | 96.7% non-empty | Slimmed from raw `reviews` to capped `{author_name, rating, text, date}` objects; null `title` dropped. | Recent review sample, not the full review population. |
| `review_snippets` | list[str] | 96.7% non-empty | Copied from raw `review_snippets`; missing becomes empty list. | Short review snippets retained for audit/text analysis. |
| `sample_size` | int | 100% | Derived as `len(reviews)`. | Number of retained nested reviews. |
| `sample_avg_rating` | float \| null | 96.7% | Mean of numeric ratings inside the retained review sample. | Sample-only quality signal; never used to backfill platform rating. |
| `rating_sample_divergent` | bool | 100% | Derived when `abs(rating - sample_avg_rating) > 1.0`. | Flags disagreement between platform rating and recent sample average. |
| `has_reviews` | bool | 100% | Derived from `reviews` being non-empty. | Review-sample coverage flag. |
| `scraped_at` | str | 100% | Copied from raw `scraped_at`. | Source scrape timestamp. |
| `source_page_number` | int | 100% | Copied from raw `source_page_number`. | Listing-page provenance. |
| `detail_scraped` | bool | 100% | Copied from raw `detail_scraped`. | Detail-enrichment provenance. |
| `flags` | list[str] | 100% | Derived reason list from quality checks. | May include `no_rating`, `missing_review_count`, `low_review`, `rating_sample_divergent`, `invalid_cuisine_type`. |
| `_transformed_at` | datetime | 100% | Added by transform at write time. | UTC transform timestamp. |
| `_source_collection` | str | 100% | Added from transform settings. | Source collection name, normally `restaurants_raw_thefork`. |
