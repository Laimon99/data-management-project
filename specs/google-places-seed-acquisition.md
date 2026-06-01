# Spec for google-places-seed-acquisition
branch: feature/google-places-seed-acquisition
## Summary
Implement a two-mode Google Places API (New) client for pipeline Stage 1 (Seed Acquisition).

**Mode 1 — venue list**: performs area-based Nearby Searches across Milan to collect all food-related venues and produce the `restaurants_seed` table (name, address, city, lat, lon, place_id).

**Mode 2 — venue detail**: for a given place_id (or list of place_ids), fetches every field the API exposes and stores a raw enriched record per venue, which feeds Google's own ratings column in the unified dataset.

## Functional Requirements
- The client must expose a clear entry point for each mode, callable independently from the CLI and importable as a module.
- **Mode 1 – Venue List**
  - Accept Milan centre coordinates and a configurable search radius (default 15 km).
  - Use the Places API (New) Nearby Search endpoint with food-related `includedTypes` covering at minimum: `restaurant`, `cafe`, `bar`, `bakery`, `meal_delivery`, `meal_takeaway`, `food_court`, `fast_food_restaurant`, `pizza_restaurant`, `coffee_shop`.
  - Handle pagination (nextPageToken) until all results are exhausted or a configurable max-results limit is reached.
  - Deduplicate results by `place_id` before writing.
  - Output each venue with at minimum: `place_id`, `name`, `formatted_address`, `city` (extracted or defaulted to "Milan"), `latitude`, `longitude`.
  - Persist results to the raw seed JSONL file `data/restaurants_seed.jsonl` (one document per venue).
- **Mode 2 – Venue Detail**
  - Accept a single `place_id` or a list/file of place_ids.
  - Request all available Place Details (New) fields via field mask, including (non-exhaustive): `rating`, `userRatingCount`, `priceLevel`, `priceRange`, `types`, `primaryType`, `websiteUri`, `regularOpeningHours`, `businessStatus`, `servesBeer`, `servesLunch`, `servesDinner`, `delivery`, `dineIn`, `takeout`, `reservable`, `reviews`.
  - Persist the full raw API response per venue in the same `restaurants_seed` document (merge/upsert by `place_id`).
  - Log which fields are absent or null per record.
- Rate limiting: respect the Places API quota; implement configurable request delay and retry with exponential backoff on 429/503 responses.
- API key must be read from environment variables only — never hardcoded.
- All output must be structured as JSON documents suitable for later import into the chosen DBMS, if/when storage is revisited.

## Possible Edge Cases
- Milan boundary ambiguity: a fixed-radius circle around city centre may miss outer neighbourhoods or include non-Milan venues; - it's okey to include non-Milan places.
- API result cap: Nearby Search (New) returns at most 20 results per call; pagination and multi-zone tiling is needed to avoid truncation for dense areas.
- Missing fields in Mode 2: many detail fields (atmosphere, hours) are not guaranteed — the client must handle partial responses without failing.
- Duplicate places at zone boundaries when tiling multiple search circles; deduplication by `place_id` is mandatory. - in single run ok, but we can handle it later.
- Venues ambiguously typed (e.g. a hotel restaurant tagged primarily as `lodging`): LLM-based post-filtering is out of scope here but the raw `types` array must be stored for later filtering.
- API key quota exhaustion mid-run: the client should checkpoint progress so a restart resumes rather than restarts.
- Network timeouts or transient 5xx errors during bulk Mode 2 fetches.

## Acceptance Criteria
- Mode 1 produces a deduplicated raw seed dataset containing at least 500 Milan food venues with all required fields populated.
- Mode 2, given the place_ids from Mode 1, enriches each seed document with Google ratings and raw detail fields without data loss.
- No venue record is silently dropped; failures are logged with the offending `place_id` and reason.
- The API key is never written to any file, log, or document.
- Re-running Mode 1 against an existing raw seed dataset upserts records rather than creating duplicates.
- Re-running Mode 2 for an already-fetched place_id overwrites only the detail fields, preserving seed fields.
- The module can be invoked from CLI with a `--mode list` or `--mode detail` flag.
- All results pass a schema validation step (required fields present and correctly typed).

## Open Questions
- Should Mode 1 use a single large-radius search centred on Piazza del Duomo, or tile the city into multiple smaller overlapping circles? The latter gives denser coverage but multiplies API calls. - multiple probably, idea to get exhaustive list
- What is the target venue count? The choice of types and radius directly affects quota usage. - doesn't matter for now, implementation of reader shouldn't depend on shuch thing - running job for getting is out of scope.
- Should `restaurants_seed` also store Google's own `rating` and `userRatingCount` collected during Mode 1 (from the Nearby Search response), or defer all ratings to Mode 2? - if it doesn't cost anything better to get it multiple times
- Is there a budget/quota limit to plan around (free tier vs. paid plan)? - free tier for now but implementation shouldn't consider this question, only error handling around it.

## Out of Scope
- Tripadvisor and TheFork data collection (separate pipeline stages).
- Entity resolution / matching across platforms.
- LLM-based filtering of misclassified venues (later stage).
- Geocoding or re-geocoding addresses — coordinates come directly from the API response.
- Review text scraping beyond what the Places API (New) natively provides.

## Feature Testing Guidelines
Create a test file(s) in the /tests folder for the new feature, and create meaningful tests for the following cases, without going too heavy:
- Mock the Places API Nearby Search response and assert that Mode 1 correctly parses, deduplicates, and stores venue documents.
- Mock a paginated response (with `nextPageToken`) and assert that all pages are consumed.
- Mock a Place Details response with several null fields and assert that the client stores the partial record without raising an exception.
- Assert that a second Mode 1 run with the same mock data upserts rather than duplicates.
- Assert that the API key is sourced from the environment and that a missing key raises a clear error before any network call.
- Assert that a 429 response triggers a retry with backoff rather than an immediate failure.
