# Clean Dataset Schema - `restaurants_clean_google`

Output of the `google_clean` transform (`uv run google-clean`), Mongo -> Mongo. The
tables below describe fields in the clean output, not the full raw input. Fields that
are copied unchanged from the raw top-level record appear only in the first table. Fields
that are normalized, renamed, lifted from `details`, derived, or created by the transform
appear only in the second table.

Coverage for the clean table is from a full run: **10,786 clean documents** from
**10,808 raw records** after dropping 22 inert junk records. Raw-only inputs such as the
full `details` blob, `details_fetched_at`, and `seed_collected_at` remain in
`restaurants_raw_google` and are not clean-schema fields.

## Schema Overview

| Semantic group | Fields |
|---|---|
| Identity | `_id`, `place_id`, `name` |
| Coordinates | `latitude`, `longitude` |
| Address | `address`, `street`, `street_number`, `postal_code`, `locality`, `province`, `country`, `city`, `city_out_of_area` |
| Ratings | `rating`, `review_count`, `has_rating`, `low_review` |
| Classification | `primary_type`, `types`, `category_tier`, `is_dining` |
| Operational quality | `business_status`, `is_operational`, `name_is_geographic`, `flags` |
| Price and contacts | `price_level`, `price_range`, `website`, `phone`, `has_website`, `has_phone` |
| Source richness | `photo_count`, `reviews` |
| Services and amenities | `dine_in`, `takeout`, `delivery`, `reservable`, `curbside_pickup`, `outdoor_seating`, `serves_vegetarian_food`, `serves_breakfast`, `serves_lunch`, `serves_dinner`, `serves_beer`, `serves_wine`, `serves_cocktails`, `serves_coffee`, `serves_dessert`, `live_music`, `good_for_children`, `good_for_groups`, `allows_dogs`, `restroom`, `menu_for_children`, `good_for_watching_sports` |
| Transform metadata | `_transformed_at`, `_source_collection` |

## Old Features - Kept Unchanged

| Field | Type | Coverage | Description |
|---|---|---:|---|
| `place_id` | str | 100% | Google Places natural key, copied unchanged. |
| `latitude` | float | 100% | Authoritative Google latitude, copied unchanged and never re-geocoded. |
| `longitude` | float | 100% | Authoritative Google longitude, copied unchanged and never re-geocoded. |
| `primary_type` | str \| null | 99.8% | Google's main category type, copied unchanged. |
| `types` | list[str] | 100% | Full Google type-tag list, copied unchanged. |

## New Or Transformed Features

| Field | Type | Coverage | Transformed | Description |
|---|---|---:|---|---|
| `_id` | str | 100% | Created from `place_id`. | Mongo key for idempotent upserts. |
| `name` | str \| null | 100% | Normalized from raw `name`: whitespace collapsed, ALL-CAPS recased best-effort. | Clean display name for matching and reporting. |
| `address` | str \| null | 100% | Normalized from raw `formatted_address`. | Full clean address string. |
| `street` | str \| null | 98.2% | Derived from `details.addressComponents` route component. | Street name. |
| `street_number` | str \| null | 92.4% | Derived from `details.addressComponents` street-number component. | Civic number. |
| `postal_code` | str \| null | 100% | Derived from `details.addressComponents` postal-code component. | Italian CAP. |
| `locality` | str \| null | 97.2% | Derived from `details.addressComponents` locality component. | Raw locality before city canonicalization. |
| `province` | str \| null | 100% | Derived from `details.addressComponents` administrative-area component. | Province code, usually `MI`. |
| `country` | str \| null | 100% | Derived from `details.addressComponents` country component. | Country name. |
| `city` | str \| null | 100% | Derived from locality with raw `city` fallback; `Milan` normalized to `Milano`. | Canonical city string for blocking and analysis. |
| `city_out_of_area` | bool | 100% | Created by checking canonical `city` against known out-of-area names. | Quality flag for city labels outside the Milan-area scope. |
| `rating` | float \| null | 93.7% | Coalesced from `details.rating`, then raw `rating`; validated to 1-5. | Google aggregate rating. |
| `review_count` | int \| null | 93.7% | Coalesced from `details.userRatingCount`, then raw `user_rating_count`; renamed. | Google review count. |
| `has_rating` | bool | 100% | Created from `rating is not null`. | Rating coverage flag. |
| `low_review` | bool | 100% | Created from `review_count < low_review_threshold` when count exists. | Count-only quality flag; records are kept. |
| `category_tier` | str | 100% | Created from `primary_type` and `types`. | `restaurant`, `cafe_bar_bakery`, `non_dining`, or `unknown`. |
| `is_dining` | bool | 100% | Created from `category_tier`. | True for categories in scope for restaurant matching. |
| `business_status` | str \| null | 100% | Lifted and renamed from `details.businessStatus`. | Operational status from Google. |
| `is_operational` | bool | 100% | Created from `business_status == "OPERATIONAL"`. | Operational-quality flag. |
| `name_is_geographic` | bool | 100% | Created from name/locality heuristics. | Flags geographic placeholder names rather than venues. |
| `flags` | list[str] | 15.4% non-empty | Created as a reason list from quality/relevance checks; field is present on every document. | May include `non_dining`, `name_is_geographic`, `not_operational`, `low_review`, `city_out_of_area`; empty list when no flags apply. |
| `photo_count` | int | 100% | Created as `len(details.photos)`. | Photo metadata count, a source-richness feature. |
| `price_level` | str \| null | 44.7% | Lifted and renamed from `details.priceLevel`. | Google categorical price tier. |
| `price_range` | obj \| null | 73.9% | Parsed from `details.priceRange` into `{start, end, currency}`. | Numeric EUR price range. |
| `website` | str \| null | 53.3% | Lifted from `details.websiteUri`; trimmed; blanks to null. | Venue website used as matching evidence when available. |
| `phone` | str \| null | 83.7% | Lifted from `details.internationalPhoneNumber` with national fallback; trimmed; blanks to null. | Venue phone used as matching evidence when available. |
| `has_website` | bool | 100% | Created from `website is not null`. | Website coverage flag. |
| `has_phone` | bool | 100% | Created from `phone is not null`. | Phone coverage flag. |
| `dine_in` | bool | 89.1% | Snake-cased from `details.dineIn`; emitted only when supplied. | Service flag; missing means unknown, not false. |
| `takeout` | bool | 70.2% | Snake-cased from `details.takeout`; emitted only when supplied. | Service flag; missing means unknown, not false. |
| `delivery` | bool | 64.6% | Snake-cased from `details.delivery`; emitted only when supplied. | Service flag; missing means unknown, not false. |
| `reservable` | bool | 53.3% | Snake-cased from `details.reservable`; emitted only when supplied. | Service flag; missing means unknown, not false. |
| `curbside_pickup` | bool | 26.5% | Snake-cased from `details.curbsidePickup`; emitted only when supplied. | Service flag; missing means unknown, not false. |
| `outdoor_seating` | bool | 49.1% | Snake-cased from `details.outdoorSeating`; emitted only when supplied. | Amenity flag; missing means unknown, not false. |
| `serves_vegetarian_food` | bool | 21.1% | Snake-cased from `details.servesVegetarianFood`; emitted only when supplied. | Cuisine/service flag; missing means unknown, not false. |
| `serves_breakfast` | bool | 40.0% | Snake-cased from `details.servesBreakfast`; emitted only when supplied. | Meal-service flag; missing means unknown, not false. |
| `serves_lunch` | bool | 53.3% | Snake-cased from `details.servesLunch`; emitted only when supplied. | Meal-service flag; missing means unknown, not false. |
| `serves_dinner` | bool | 47.3% | Snake-cased from `details.servesDinner`; emitted only when supplied. | Meal-service flag; missing means unknown, not false. |
| `serves_beer` | bool | 75.2% | Snake-cased from `details.servesBeer`; emitted only when supplied. | Beverage flag; missing means unknown, not false. |
| `serves_wine` | bool | 69.2% | Snake-cased from `details.servesWine`; emitted only when supplied. | Beverage flag; missing means unknown, not false. |
| `serves_cocktails` | bool | 54.6% | Snake-cased from `details.servesCocktails`; emitted only when supplied. | Beverage flag; missing means unknown, not false. |
| `serves_coffee` | bool | 58.0% | Snake-cased from `details.servesCoffee`; emitted only when supplied. | Beverage flag; missing means unknown, not false. |
| `serves_dessert` | bool | 56.3% | Snake-cased from `details.servesDessert`; emitted only when supplied. | Meal-service flag; missing means unknown, not false. |
| `live_music` | bool | 72.5% | Snake-cased from `details.liveMusic`; emitted only when supplied. | Amenity flag; missing means unknown, not false. |
| `good_for_children` | bool | 52.0% | Snake-cased from `details.goodForChildren`; emitted only when supplied. | Audience flag; missing means unknown, not false. |
| `good_for_groups` | bool | 46.3% | Snake-cased from `details.goodForGroups`; emitted only when supplied. | Audience flag; missing means unknown, not false. |
| `allows_dogs` | bool | 43.7% | Snake-cased from `details.allowsDogs`; emitted only when supplied. | Amenity flag; missing means unknown, not false. |
| `restroom` | bool | 83.6% | Snake-cased from `details.restroom`; emitted only when supplied. | Amenity flag; missing means unknown, not false. |
| `menu_for_children` | bool | 32.0% | Snake-cased from `details.menuForChildren`; emitted only when supplied. | Menu flag; missing means unknown, not false. |
| `good_for_watching_sports` | bool | 53.5% | Snake-cased from `details.goodForWatchingSports`; emitted only when supplied. | Amenity flag; missing means unknown, not false. |
| `reviews` | list[obj] | 93.7% non-empty | Slimmed from `details.reviews` to `{rating, text, language, publish_time, author}`; field is present on every document. | Capped recent-review sample; empty list when no reviews. |
| `_transformed_at` | datetime | 100% | Added by transform at write time. | UTC transform timestamp. |
| `_source_collection` | str | 100% | Added from transform settings. | Source collection name, normally `restaurants_raw_google`. |

## Deleted Or Replaced Raw Fields

| Raw Field | Type | Coverage | Deleted / Replaced By | Reason |
|---|---|---:|---|---|
| `formatted_address` | str | 100% | `address` | Replaced by normalized full address. |
| `city` | str | 100% | `city` | Replaced by canonical city derived mainly from structured address components. |
| `user_rating_count` | int \| null | 94% | `review_count` | Renamed and coalesced with fresher `details.userRatingCount`. |
| `details` | obj | 100% | Selected clean fields | Heavy raw Places Details blob is not copied; only selected fields are lifted/parsed. |
| `details_fetched_at` | str | 100% | raw audit only | Extraction timestamp stays in `restaurants_raw_google`. |
| `seed_collected_at` | str | 100% | raw audit only | Seed-acquisition timestamp stays in `restaurants_raw_google`. |
