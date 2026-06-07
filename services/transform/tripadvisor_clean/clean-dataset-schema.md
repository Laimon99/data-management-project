# Clean Dataset Schema — `restaurants_clean_tripadvisor`

Output of the `tripadvisor_clean` transform (`uv run tripadvisor-clean`), Mongo → Mongo.
One document per Tripadvisor venue, keyed on `source_url` (→ `_id`). The raw record stays
in `restaurants_raw_tripadvisor` as the immutable audit trail / LLM-extension source; the
replaced raw strings (`number_photo_uploaded`, `price_range`, `cuisine_type`,
`working_days_hours`, `review`) are **dropped** from the clean document.

Coverage figures are from a full deterministic pass over the **7,539** raw records.
“Coverage” = % of documents where the field is non-null (for `has_*`/`flags`, always
present). Coordinate coverage is **geocoding-dependent** (a `--skip-geocode` run leaves
them null).

**Source legend:** `passthrough` (natural key, verbatim) · `normalized` (cleaned/recased)
· `repaired` (Italian display string → typed value) · `derived` (parsed/lifted/computed) ·
`flag` (boolean quality signal) · `feature` (derived analytic feature) · `metadata`
(transform bookkeeping). **NEW** marks fields that did not exist in the raw record.

---

## Identity & key

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `_id` | str | 100% | passthrough | Mongo key = `source_url`. |
| `source_url` | str | 100% | passthrough | Tripadvisor review URL (natural key). |
| `ta_location_id` | str \| null | 100% | **NEW** derived | Stable venue id (the `-d<n>-` URL token) — join/blocking key. |
| `restaurant_name` | str \| null | 100% | normalized | Display name, whitespace-collapsed. |

## Location (geocoded — Tripadvisor ships no coordinates)

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `latitude` | float \| null | geocode-dependent | **NEW** derived | WGS-84 latitude from Nominatim on the cleaned address. |
| `longitude` | float \| null | geocode-dependent | **NEW** derived | WGS-84 longitude from Nominatim on the cleaned address. |
| `has_coordinates` | bool | 100% | **NEW** flag | Both coordinates present. |

## Address (structured extraction on top of normalized `address`)

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `address` | str \| null | 99.1% | normalized | Full address line, whitespace/separator-normalized. |
| `street` | str \| null | 99.1% | **NEW** derived | Street part (text before the CAP). |
| `postal_code` | str \| null | 95.9% | **NEW** derived | Italian CAP (5-digit). |
| `city` | str \| null | 95.9% | **NEW** derived | City (text after the CAP, country stripped). |
| `has_address` | bool | 100% | **NEW** flag | `address is not null`. |

## Ratings & reviews

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `rating` | float \| null | 99.8% | repaired | Tripadvisor rating 1.0–5.0 (`"5,0"` → `5.0`); out-of-range/garbage → null. |
| `total_review` | int \| null | 100% | repaired | Platform review count (`"(1.234 recensioni)"` → `1234`). |
| `has_rating` | bool | 100% | **NEW** flag | `rating is not null`. |
| `has_review_count` | bool | 100% | **NEW** flag | `total_review is not null`. |
| `low_review` | bool | 100% | **NEW** flag | `total_review < low_review_threshold` (default 10); **count-only**. |

## Features (parsed from raw display strings)

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `photo_count` | int \| null | 78.9% | **NEW** derived | From `number_photo_uploaded` (thousands separators handled). |
| `price_band` | str \| null | 67.7% | **NEW** derived | Source euro-symbol band (`"€"`, `"€€-€€€"`, `"€€€€"`). |
| `price_tier_level` | int \| null | 67.7% | **NEW** derived | Ordinal tier = €-count of the band's lower bound (€→1, €€-€€€→2, €€€€→4). |
| `cuisines` | list[str] | 77.7% (non-empty) | **NEW** derived | Cuisine tokens, trimmed, de-duped case-insensitively (source vocabulary, 56 distinct tokens). Empty list when absent. |
| `opening_hours` | list[obj] | 67.6% (non-empty) | **NEW** derived | `[{day, opens, closes[, closes_next_day]}]`, English day names, split shifts preserved, `Chiuso` days omitted. Empty list when absent/malformed. |
| `reviews` | list[obj] | 88.6% (non-empty) | **NEW** feature | ≤ `review_cap` (default 20) reviews `{nickname, contributions, title, text, date}`; `"Scopri di più"` suffix stripped, Italian date → ISO. Empty list when none. |
| `sample_size` | int | 100% | **NEW** feature | `len(reviews)` — a recent first-page sample (≤15 observed), **not** `total_review`. |
| `has_reviews` | bool | 100% | **NEW** flag | `reviews` non-empty. |
| `has_hours` | bool | 100% | **NEW** flag | `opening_hours` non-empty. |

## Contacts (normalized — Tripadvisor contacts are real, unlike TheFork's)

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `website` | str \| null | 79.9% | normalized | Own site or social link; `"NaN"`/blank → null. |
| `phone_number` | str \| null | 90.1% | normalized | Phone as displayed; `"NaN"`/blank → null. |
| `email` | str \| null | 46.9% | normalized | Contact email; `"NaN"`/blank → null. |
| `has_website` / `has_phone` / `has_email` | bool | 100% | **NEW** flag | Respective contact present. |

## Quality flags

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `flags` | list[str] | 100% | **NEW** | Reason list (may be empty): `no_rating`, `missing_review_count`, `low_review`, `missing_address`, `geocode_not_found`, `missing_coordinates`, `rating_with_zero_reviews`, `no_reviews`, `no_hours`. |

## Metadata

| Field | Type | Coverage | Source | Description |
|---|---|---|---|---|
| `_transformed_at` | datetime | 100% | metadata | UTC timestamp of the transform run. |
| `_source_collection` | str | 100% | metadata | `restaurants_raw_tripadvisor`. |

---

## Example document (abridged)

```json
{
  "_id": "https://www.tripadvisor.it/Restaurant_Review-g187849-d28119476-Reviews-Dop20-Milan_Lombardy.html",
  "source_url": "https://www.tripadvisor.it/Restaurant_Review-g187849-d28119476-Reviews-Dop20-Milan_Lombardy.html",
  "ta_location_id": "28119476",
  "restaurant_name": "Dop20",
  "latitude": 45.4612, "longitude": 9.2017, "has_coordinates": true,
  "address": "Via Vincenzo Vela, 14, 20133 Milano Italia",
  "street": "Via Vincenzo Vela, 14", "postal_code": "20133", "city": "Milano",
  "has_address": true,
  "rating": 4.5, "total_review": 1234,
  "has_rating": true, "has_review_count": true, "low_review": false,
  "photo_count": 380,
  "price_band": "€€-€€€", "price_tier_level": 2,
  "cuisines": ["Italiana", "Pizza"],
  "opening_hours": [
    {"day": "monday", "opens": "12:00", "closes": "15:00"},
    {"day": "monday", "opens": "19:00", "closes": "23:00"}
  ],
  "has_hours": true,
  "reviews": [{"nickname": "alessandrocS4503UZ", "contributions": 875,
               "title": "Pausa pranzo eccellente", "text": "La miglior pausa pranzo in zona…",
               "date": "2026-05-29"}],
  "sample_size": 1, "has_reviews": true,
  "website": "https://dop20.it", "phone_number": "+39 320 559 4515", "email": null,
  "has_website": true, "has_phone": true, "has_email": false,
  "flags": [],
  "_transformed_at": "2026-06-07T10:00:00.000Z",
  "_source_collection": "restaurants_raw_tripadvisor"
}
```
