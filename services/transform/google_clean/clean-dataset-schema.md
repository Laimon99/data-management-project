# Clean Dataset Schema — `restaurants_clean_google`

Output of the `google_clean` transform (`uv run google-clean`), Mongo → Mongo. One
document per kept Google Places venue, keyed on `place_id` (→ `_id`). The heavy raw
`details` blob is **not** copied; the full raw record stays in `restaurants_raw_google`
as the audit trail / LLM-extension source.

Coverage figures below are from a full run: **10,786 documents** (10,808 raw − 22 inert
junk dropped). “Coverage” = % of documents where the field is non-null.

**Source legend:** `passthrough` (copied verbatim from the raw flat field) · `normalized`
(cleaned/recased copy) · `derived` (lifted from `details.addressComponents`/computed) ·
`flag` (boolean quality/relevance flag) · `feature` (derived analytic feature) ·
`metadata` (transform bookkeeping). **NEW** marks fields that did not exist in the raw
flat seed record (they are extracted from `details` or computed here).

---

## Identity & key

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `_id` | str | 100% | passthrough | Mongo key = `place_id`. |
| `place_id` | str | 100% | passthrough | Google Places id (natural key). |
| `name` | str \| null | 100% | normalized | Display name, whitespace-collapsed; ALL-CAPS recased to title case (best-effort). |

## Location (authoritative — never recomputed)

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `latitude` | float | 100% | passthrough | WGS-84 latitude, copied verbatim from the seed. |
| `longitude` | float | 100% | passthrough | WGS-84 longitude, copied verbatim from the seed. |

## Address (structured lookup from `details.addressComponents`)

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `address` | str \| null | 100% | normalized | Full `formatted_address`, whitespace/separator-normalized. |
| `street` | str \| null | 98.2% | **NEW** derived | `route` component. |
| `street_number` | str \| null | 92.4% | **NEW** derived | `street_number` component. |
| `postal_code` | str \| null | 100% | **NEW** derived | Italian CAP (`postal_code` component). |
| `locality` | str \| null | 97.2% | **NEW** derived | `locality` component (raw, before canonicalization). |
| `province` | str \| null | 100% | **NEW** derived | `administrative_area_level_2` short code (e.g. `MI`). |
| `country` | str \| null | 100% | **NEW** derived | `country` component (e.g. `Italy`). |
| `city` | str \| null | 100% | normalized | Canonical city: from `locality` (fallback flat `city`), recased, `Milan`→`Milano`. |
| `city_out_of_area` | bool | 100% | **NEW** flag | True when `city` names a place outside the Milan metro (e.g. `Torino`) despite in-bbox coords. |

## Ratings (canonical = `details.*`, coalesced to top-level when missing)

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `rating` | float \| null | 93.7% | normalized | Google rating 1.0–5.0; prefers `details.rating`, falls back to top-level. |
| `review_count` | int \| null | 93.7% | normalized | Review count (was `user_rating_count`); prefers `details.userRatingCount`. |
| `has_rating` | bool | 100% | **NEW** flag | `rating is not null`. |
| `low_review` | bool | 100% | **NEW** flag | `review_count < low_review_threshold` (default 10); **count-only**. |

## Classification & relevance

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `primary_type` | str \| null | 99.8% | passthrough | Google's most specific type. |
| `types` | list[str] | 100% | passthrough | All Google type tags. |
| `category_tier` | str | 100% | **NEW** derived | `restaurant` / `cafe_bar_bakery` / `non_dining` / `unknown`. |
| `is_dining` | bool | 100% | **NEW** derived | `category_tier ∈ {restaurant, cafe_bar_bakery}` (in-scope for the comparison). |

## Quality flags

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `business_status` | str \| null | 100% | passthrough | `OPERATIONAL` / `CLOSED_TEMPORARILY` / `CLOSED_PERMANENTLY`. |
| `is_operational` | bool | 100% | **NEW** flag | `business_status == "OPERATIONAL"`. |
| `name_is_geographic` | bool | 100% | **NEW** flag | Name is a region/city/CAP string (junk signal). |
| `flags` | list[str] | 100% | **NEW** | Reason list — any of `non_dining`, `name_is_geographic`, `not_operational`, `low_review`, `city_out_of_area` (may be empty). |

## Features (NEW — derived from `details`)

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `photo_count` | int | 100% | **NEW** feature | Number of photo-metadata objects Google returned (richness/popularity signal). |
| `price_level` | str \| null | 44.7% | passthrough | Categorical tier (`PRICE_LEVEL_*`). |
| `price_range` | obj \| null | 73.9% | **NEW** feature | Compacted `{start, end, currency}` (ints / EUR). |
| `has_website` | bool | 100% | **NEW** flag | Website present (non-blank). |
| `has_phone` | bool | 100% | **NEW** flag | Phone present (non-blank). |
| `website` | str \| null | 53.3% | derived | Venue website (blank → null) — matching aid. |
| `phone` | str \| null | 83.7% | derived | International (or national) phone — matching aid. |

### Amenity / service flags (NEW — **present-only**, snake-cased Google booleans)

Each is emitted **only when Google supplies it**, so documents have a heterogeneous set
(coverage = how often Google returned the flag). Downstream should treat *missing* as
*unknown*, not `False`.

| Field | Coverage | · | Field | Coverage |
|---|---|---|---|---|
| `dine_in` | 89.1% | · | `serves_beer` | 75.2% |
| `takeout` | 70.2% | · | `serves_wine` | 69.2% |
| `delivery` | 64.6% | · | `serves_cocktails` | 54.6% |
| `reservable` | 53.3% | · | `serves_coffee` | 58.0% |
| `curbside_pickup` | 26.5% | · | `serves_dessert` | 56.3% |
| `outdoor_seating` | 49.1% | · | `serves_breakfast` | 40.0% |
| `live_music` | 72.5% | · | `serves_lunch` | 53.3% |
| `good_for_children` | 52.0% | · | `serves_dinner` | 47.3% |
| `good_for_groups` | 46.3% | · | `serves_vegetarian_food` | 21.1% |
| `good_for_watching_sports` | 53.5% | · | `menu_for_children` | 32.0% |
| `allows_dogs` | 43.7% | · | `restroom` | 83.6% |

## Reviews (slimmed)

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `reviews` | list[obj] | 100% | **NEW** feature | ≤5 reviews, each `{rating, text, language, publish_time, author}`. Empty list when none. Full reviews remain in raw for the LLM extension. |

## Metadata

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `_transformed_at` | datetime | 100% | metadata | UTC timestamp of the transform run. |
| `_source_collection` | str | 100% | metadata | `restaurants_raw_google`. |

---

## Example document (abridged)

```json
{
  "_id": "ChIJ--B9MpPAhkcR5i3IsaONCho",
  "place_id": "ChIJ--B9MpPAhkcR5i3IsaONCho",
  "name": "In Piazza",
  "latitude": 45.5167039, "longitude": 9.1692377,
  "address": "Via Gaetano Osculati, 2, 20161 Milano MI, Italy",
  "street": "Via Gaetano Osculati", "street_number": "2",
  "postal_code": "20161", "locality": "Milano", "province": "MI", "country": "Italy",
  "city": "Milano", "city_out_of_area": false,
  "rating": 4.2, "review_count": 549, "has_rating": true, "low_review": false,
  "primary_type": "restaurant", "types": ["restaurant", "pizza_restaurant", "..."],
  "category_tier": "restaurant", "is_dining": true,
  "business_status": "OPERATIONAL", "is_operational": true,
  "name_is_geographic": false, "flags": [],
  "photo_count": 10, "price_level": "PRICE_LEVEL_INEXPENSIVE",
  "price_range": {"start": 10, "end": 20, "currency": "EUR"},
  "has_website": true, "has_phone": true,
  "website": "http://www.inpiazzaaffori.it/", "phone": "+39 02 645 6224",
  "dine_in": true, "takeout": true, "reservable": true, "serves_wine": true,
  "reviews": [{"rating": 5, "text": "...", "language": "en",
               "publish_time": "2026-05-01T...", "author": "Marco R."}],
  "_transformed_at": "2026-06-06T19:23:04.857Z",
  "_source_collection": "restaurants_raw_google"
}
```
