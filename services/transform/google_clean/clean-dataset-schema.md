# Clean Dataset Schema - `restaurants_clean_google`

Output of the `google_clean` transform (`uv run google-clean`), Mongo -> Mongo. The
raw input is `restaurants_raw_google`; the clean output is one lean document per kept
Google Places venue in `restaurants_clean_google`, keyed by `place_id` (`_id`).

Coverage for the clean table is from a full run: **10,786 clean documents** from
**10,808 raw records** after dropping 22 inert junk records. "Coverage" means non-null
coverage unless the description says "non-empty" for arrays. Raw coverage comes from
the Google Places seed schema.

## Old Features - Raw Source Schema

| Field | Type | Coverage | Description |
|---|---|---:|---|
| `place_id` | str | 100% | Google Places natural key. |
| `name` | str | 100% | Raw venue display name. |
| `formatted_address` | str | 100% | Full formatted address from Places search. |
| `city` | str | 100% | Raw city string from the seed. It is not fully reliable and includes Milan/Milano spelling drift plus some out-of-area values. |
| `latitude` | float | 100% | WGS-84 latitude from Google. Used as authoritative seed coordinate. |
| `longitude` | float | 100% | WGS-84 longitude from Google. Used as authoritative seed coordinate. |
| `types` | list[str] | 100% | Google place type tags. |
| `primary_type` | str | 100% | Google's primary type for the place. |
| `rating` | float \| null | 94% | Top-level Google aggregate rating on a 1-5 scale. |
| `user_rating_count` | int \| null | 94% | Top-level Google review count. |
| `details` | obj | 100% | Full Places Details response. Kept only in the raw collection. |
| `details.addressComponents` | list[obj] | 100% | Structured address parts used to derive street, number, postal code, locality, province, and country. |
| `details.rating` | float \| null | 94% | Details-level aggregate rating, preferred over the top-level value when present. |
| `details.userRatingCount` | int \| null | 94% | Details-level review count, preferred over the top-level value when present. |
| `details.businessStatus` | str \| null | about 100% | Operational status used for quality flags. |
| `details.priceLevel` | str \| null | 45% | Google's categorical price tier. |
| `details.priceRange` | obj \| null | 74% | Numeric price range with currency and units. |
| `details.websiteUri` | str \| null | 53% | Venue website URL when Google returns it. |
| `details.internationalPhoneNumber` | str \| null | 84% | International phone number, preferred over national format. |
| `details.nationalPhoneNumber` | str \| null | 84% | National phone number fallback. |
| `details.photos` | list[obj] | 91% | Up to 10 Google photo metadata objects. |
| `details.reviews` | list[obj] | 94% | Up to 5 recent Google reviews in the full Places Details shape. |
| `details.service_amenity_flags` | bool fields | varies | Google booleans such as `dineIn`, `takeout`, `servesBeer`, `outdoorSeating`, and similar service/amenity flags. |
| `details_fetched_at` | str | 100% | Timestamp of the Places Details fetch. Kept in raw only. |
| `seed_collected_at` | str | 100% | Timestamp of seed acquisition. Kept in raw only. |

## New Features - Clean Schema

| Field | Type | Coverage | Transformed | Description |
|---|---|---:|---|---|
| `_id` | str | 100% | Created from `place_id`. | Mongo key for idempotent upserts. |
| `place_id` | str | 100% | Copied from raw `place_id`. | Google Places natural key. |
| `name` | str \| null | 100% | Whitespace collapsed; ALL-CAPS names recased best-effort. | Clean display name for matching and reporting. |
| `latitude` | float | 100% | Copied from raw `latitude`; never re-geocoded. | Canonical latitude when Google is part of a match. |
| `longitude` | float | 100% | Copied from raw `longitude`; never re-geocoded. | Canonical longitude when Google is part of a match. |
| `address` | str \| null | 100% | Normalized from raw `formatted_address`. | Full clean address string. |
| `street` | str \| null | 98.2% | Derived from `details.addressComponents` route component. | Street name. |
| `street_number` | str \| null | 92.4% | Derived from `details.addressComponents` street-number component. | Civic number. |
| `postal_code` | str \| null | 100% | Derived from `details.addressComponents` postal-code component. | Italian CAP. |
| `locality` | str \| null | 97.2% | Derived from `details.addressComponents` locality component. | Raw locality before city canonicalization. |
| `province` | str \| null | 100% | Derived from `details.addressComponents` administrative-area component. | Province code, usually `MI`. |
| `country` | str \| null | 100% | Derived from `details.addressComponents` country component. | Country name. |
| `city` | str \| null | 100% | Derived from locality with raw `city` fallback; `Milan` normalized to `Milano`. | Canonical city string for blocking and analysis. |
| `city_out_of_area` | bool | 100% | Derived by checking canonical `city` against known out-of-area names. | Quality flag for records whose city label conflicts with the Milan-area scope. |
| `rating` | float \| null | 93.7% | Coalesced from `details.rating`, then raw `rating`; validated to 1-5. | Google aggregate rating. |
| `review_count` | int \| null | 93.7% | Coalesced from `details.userRatingCount`, then raw `user_rating_count`; renamed. | Google review count. |
| `has_rating` | bool | 100% | Derived from `rating is not null`. | Rating coverage flag. |
| `low_review` | bool | 100% | Derived from `review_count < low_review_threshold` when count exists. | Count-only quality flag; records are kept. |
| `primary_type` | str \| null | 99.8% | Copied from raw `primary_type`. | Google's main category type. |
| `types` | list[str] | 100% | Copied from raw `types`; missing converted to empty list. | Full Google type vocabulary for the venue. |
| `category_tier` | str | 100% | Derived from `primary_type` and `types`. | `restaurant`, `cafe_bar_bakery`, `non_dining`, or `unknown`. |
| `is_dining` | bool | 100% | Derived from `category_tier`. | True for restaurant/cafe/bar/bakery categories in scope for matching. |
| `business_status` | str \| null | 100% | Lifted from `details.businessStatus`. | Operational status from Google. |
| `is_operational` | bool | 100% | Derived from `business_status == "OPERATIONAL"`. | Operational-quality flag. |
| `name_is_geographic` | bool | 100% | Derived from name/locality heuristics. | Flags geographic placeholder names rather than venues. |
| `flags` | list[str] | 100% | Derived reason list. | May include `non_dining`, `name_is_geographic`, `not_operational`, `low_review`, `city_out_of_area`. |
| `photo_count` | int | 100% | Derived as `len(details.photos)`. | Photo metadata count, a source-richness feature. |
| `price_level` | str \| null | 44.7% | Lifted from `details.priceLevel`. | Google categorical price tier. |
| `price_range` | obj \| null | 73.9% | Parsed from `details.priceRange` into `{start, end, currency}`. | Numeric EUR price range. |
| `has_website` | bool | 100% | Derived from cleaned `website`. | Website coverage flag. |
| `has_phone` | bool | 100% | Derived from cleaned `phone`. | Phone coverage flag. |
| `website` | str \| null | 53.3% | Trimmed from `details.websiteUri`; blanks to null. | Venue website used as matching evidence when available. |
| `phone` | str \| null | 83.7% | Trimmed from `details.internationalPhoneNumber` with national fallback. | Venue phone used as matching evidence when available. |
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
| `reviews` | list[obj] | 100% | Slimmed from `details.reviews` to `{rating, text, language, publish_time, author}`. | Capped recent-review sample; empty list when no reviews. |
| `_transformed_at` | datetime | 100% | Added by transform at write time. | UTC transform timestamp. |
| `_source_collection` | str | 100% | Added from transform settings. | Source collection name, normally `restaurants_raw_google`. |
