# Dataset Schema — Stage 1 Seed (`restaurants_seed.jsonl`)

Each line is a JSON object representing one restaurant in the Milan area collected via the Google Places API (New).
Total records: **10,808**.

Raw file path: `data/raw/google_places/restaurants_seed.jsonl`.

---

## Top-level fields

| Field | Type | Coverage | Description |
|---|---|---|---|
| `place_id` | string | 100% | Google Places unique identifier (e.g. `ChIJ...`). Primary key. |
| `name` | string | 100% | Display name of the venue. |
| `formatted_address` | string | 100% | Full postal address as returned by the Places search. |
| `city` | string | 100% | Always `"Milan"` — the seed is scoped to this city. |
| `latitude` | float | 100% | WGS-84 latitude. Authoritative; not re-geocoded in later stages. |
| `longitude` | float | 100% | WGS-84 longitude. Authoritative; not re-geocoded in later stages. |
| `types` | list[string] | 100% | All Google place type tags (e.g. `["restaurant", "food", "point_of_interest"]`). |
| `primary_type` | string | 100% | The single most specific type (e.g. `"restaurant"`, `"cafe"`). |
| `rating` | float \| null | 94% | Aggregate Google rating (1–5). Null for venues with no ratings. |
| `user_rating_count` | int \| null | 94% | Total number of Google reviews. Null when `rating` is null. |
| `details` | object | 100% | Full Places API detail response. See section below. |
| `details_fetched_at` | string (ISO 8601) | 100% | UTC timestamp of when the detail fetch completed. |
| `seed_collected_at` | string (ISO 8601) | 100% | UTC timestamp of when the record was first added to the seed. |

---

## `details` object

The raw response from `GET places/{place_id}`. Fields are present only when Google returns them — coverage figures are based on the 10,808-record dataset.

### Identity & location

| Field | Type | Coverage | Description |
|---|---|---|---|
| `id` | string | 100% | Same value as the top-level `place_id`. |
| `name` | string | 100% | Resource name in Places API format: `places/{place_id}`. |
| `displayName` | `{text, languageCode}` | 100% | Localised display name with its language tag. |
| `primaryType` | string | 100% | Most specific place type. Matches top-level `primary_type`. |
| `primaryTypeDisplayName` | `{text, languageCode}` | 100% | Human-readable label for `primaryType` (e.g. `"Restaurant"`). |
| `types` | list[string] | 100% | All place type tags. Matches top-level `types`. |
| `formattedAddress` | string | 100% | Full postal address. |
| `shortFormattedAddress` | string | 100% | Abbreviated address (street + number only). |
| `addressComponents` | list[object] | 100% | Structured address broken into components (`street_number`, `route`, `locality`, `postal_code`, etc.), each with `longText`, `shortText`, `types`, `languageCode`. |
| `adrFormatAddress` | string | 100% | Address as an [adr microformat](https://microformats.org/wiki/adr) HTML string. |
| `postalAddress` | object | 100% | Structured postal address (`regionCode`, `postalCode`, `adminArea`, `locality`, `addressLines`). |
| `plusCode` | `{globalCode, compoundCode}` | 100% | [Open Location Code](https://maps.google.com/pluscodes/) for the venue. |
| `location` | `{latitude, longitude}` | 100% | Coordinates (duplicates top-level `latitude`/`longitude`). |
| `viewport` | `{low, high}` | 100% | Recommended map viewport bounding box for displaying the place. |
| `addressDescriptor` | object | 100% | Landmark-based address description (nearby landmarks and areas). |
| `containingPlaces` | list[object] | varies | Parent places that contain this venue (e.g. a shopping centre). |
| `timeZone` | `{id}` | 100% | IANA time zone identifier (always `"Europe/Rome"` for this dataset). |
| `utcOffsetMinutes` | int | 100% | UTC offset in minutes at fetch time (e.g. `120` for CEST). |
| `businessStatus` | string | ~100% | Operational status: `OPERATIONAL`, `CLOSED_TEMPORARILY`, or `CLOSED_PERMANENTLY`. |
| `pureServiceAreaBusiness` | bool | varies | True if the business has no fixed customer-facing location. |

### Ratings & reviews

| Field | Type | Coverage | Description |
|---|---|---|---|
| `rating` | float | 94% | Aggregate Google rating (1.0–5.0). |
| `userRatingCount` | int | 94% | Total number of Google reviews. |
| `reviews` | list[object] | 94% | Up to 5 recent reviews. Each review contains: `name` (resource path), `rating` (1–5 int), `text` (`{text, languageCode}`), `originalText` (`{text, languageCode}`), `authorAttribution` (`{displayName, uri, photoUri}`), `publishTime` (ISO 8601), `relativePublishTimeDescription` (e.g. `"2 months ago"`), `flagContentUri`, `googleMapsUri`. |
| `editorialSummary` | `{text, languageCode}` \| null | 10% | Short editorial blurb written by Google editors. Sparse. |

### Contact & web

| Field | Type | Coverage | Description |
|---|---|---|---|
| `nationalPhoneNumber` | string | 84% | Phone number in national format (e.g. `02 1234567`). |
| `internationalPhoneNumber` | string | 84% | Phone number in E.164 / international format (e.g. `+39 02 1234567`). |
| `websiteUri` | string | 53% | Venue's own website URL. |
| `googleMapsUri` | string | 100% | Direct Google Maps URL for this place. |
| `googleMapsLinks` | object | 100% | Deep-link URLs: `placeUri`, `directionsUri`, `writeAReviewUri`, `reviewsUri`, `photosUri`. |

### Opening hours

| Field | Type | Coverage | Description |
|---|---|---|---|
| `regularOpeningHours` | object | 87% | Weekly schedule. Contains `periods` (list of open/close day+time objects), `weekdayDescriptions` (list of 7 human-readable strings), `openNow` (bool at fetch time). |
| `currentOpeningHours` | object | varies | Like `regularOpeningHours` but reflects any active special hours at fetch time. |
| `regularSecondaryOpeningHours` | list[object] | varies | Secondary schedules (e.g. delivery hours, takeout hours) in the same structure as `regularOpeningHours`. |
| `currentSecondaryOpeningHours` | list[object] | varies | Current version of secondary hours. |

### Pricing

| Field | Type | Coverage | Description |
|---|---|---|---|
| `priceLevel` | string | 45% | Categorical tier: `PRICE_LEVEL_INEXPENSIVE`, `PRICE_LEVEL_MODERATE`, `PRICE_LEVEL_EXPENSIVE`, `PRICE_LEVEL_VERY_EXPENSIVE`. |
| `priceRange` | `{startPrice, endPrice}` | 74% | Numeric range where each price is `{currencyCode: "EUR", units: "20"}`. More granular than `priceLevel`. |

### Service options

| Field | Type | Coverage | Description |
|---|---|---|---|
| `dineIn` | bool | 89% | Offers in-person dining. |
| `takeout` | bool | 70% | Offers takeout. |
| `delivery` | bool | 65% | Offers delivery. |
| `curbsidePickup` | bool | varies | Offers curbside pickup. |
| `reservable` | bool | 53% | Accepts reservations. |

### Menu & cuisine flags

| Field | Type | Coverage | Description |
|---|---|---|---|
| `servesBreakfast` | bool | varies | Serves breakfast. |
| `servesBrunch` | bool | varies | Serves brunch. |
| `servesLunch` | bool | varies | Serves lunch. |
| `servesDinner` | bool | varies | Serves dinner. |
| `servesBeer` | bool | varies | Serves beer. |
| `servesWine` | bool | varies | Serves wine. |
| `servesCocktails` | bool | varies | Serves cocktails. |
| `servesCoffee` | bool | varies | Serves coffee. |
| `servesDessert` | bool | varies | Serves dessert. |
| `servesVegetarianFood` | bool | varies | Has vegetarian options. |

### Atmosphere & amenities

| Field | Type | Coverage | Description |
|---|---|---|---|
| `outdoorSeating` | bool | varies | Has outdoor seating. |
| `liveMusic` | bool | varies | Hosts live music. |
| `menuForChildren` | bool | varies | Has a children's menu. |
| `goodForChildren` | bool | varies | Suitable for children. |
| `goodForGroups` | bool | varies | Suitable for groups. |
| `goodForWatchingSports` | bool | varies | Good for watching sports. |
| `allowsDogs` | bool | varies | Allows dogs. |
| `restroom` | bool | varies | Has a restroom available to customers. |

### Accessibility

| Field | Type | Coverage | Description |
|---|---|---|---|
| `accessibilityOptions` | object | varies | Contains boolean flags: `wheelchairAccessibleEntrance`, `wheelchairAccessibleRestroom`, `wheelchairAccessibleSeating`, `wheelchairAccessibleParking`. |

### Payment & parking

| Field | Type | Coverage | Description |
|---|---|---|---|
| `paymentOptions` | object | varies | Boolean flags: `acceptsCreditCards`, `acceptsDebitCards`, `acceptsCashOnly`, `acceptsNfc`. |
| `parkingOptions` | object | varies | Boolean flags: `paidParkingLot`, `freeParkingLot`, `freeStreetParking`, `paidStreetParking`, `valetParking`, `freeGarage`, `paidGarage`. |

### Photos

| Field | Type | Coverage | Description |
|---|---|---|---|
| `photos` | list[object] | 91% | Up to 10 photo metadata objects. Each contains: `name` (resource path usable to fetch the image via `GET /v1/{name}/media`), `widthPx`, `heightPx`, `authorAttributions` (`[{displayName, uri, photoUri}]`), `flagContentUri`, `googleMapsUri`. Pixel data is not stored — use the `name` path to download on demand. |

### Internal / UI metadata

| Field | Type | Coverage | Description |
|---|---|---|---|
| `iconMaskBaseUri` | string | 100% | Base URL for the place's category icon (SVG mask). |
| `iconBackgroundColor` | string | 100% | Hex colour to use behind the category icon (e.g. `"#FF9E67"`). |
| `googleMapsTypeLabel` | `{text, languageCode}` | 100% | Localised category label shown on Google Maps (e.g. `"Ristorante"`). |
| `fuelOptions` | object | rare | Fuel pricing info; present only for petrol-station-adjacent records. |
