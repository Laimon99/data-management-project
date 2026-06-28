# Integrated Dataset Schema - `restaurants_integrated`

One document represents one Google-seeded restaurant entity:

```text
_id = integrated_restaurant_id = "google:" + google.place_id
```

Only Google records with `is_dining=true` and `is_operational=true` are emitted.

## Top-Level Fields

| Group | Fields |
|---|---|
| Identity/geography | `integrated_restaurant_id`, `canonical_name`, `canonical_address`, `canonical_street`, `canonical_house_number`, `canonical_postal_code`, `canonical_city`, `latitude`, `longitude`, `coordinate_source` |
| Platform membership | `has_google`, `has_tripadvisor`, `has_thefork`, `has_all_three_platforms`, `platform_count` |
| Comparable ratings | `google_rating_5`, `tripadvisor_rating_5`, `thefork_rating_raw_10`, `thefork_rating_5`, `rating_platform_count`, `rating_avg_5`, `rating_range_5` |
| Comparable review counts | `google_review_count`, `tripadvisor_review_count`, `thefork_review_count` |
| Canonical cuisine | `cuisine_tags`, `cuisine_primary`, `cuisine_primary_source`, `cuisine_n_sources`, `cuisine_agreement` |
| Top-level contacts/price | `website`, `website_source`, `website_match_status`, `website_evidence`, `phones`, `phone_match_status`, `phone_evidence`, `price_level`, `price_level_source`, `price_evidence` |
| Audit | `integration_flags`, `_updated_at` |
| Source evidence | `sources.google`, `sources.tripadvisor`, `sources.thefork` |

## Canonical Cuisine

The three platforms speak three cuisine vocabularies — Tripadvisor uses Italian feminine
adjectives (`Italiana`), TheFork masculine (`Italiano`) plus regional Italians, and Google an
English `primary_type`/`types[]` controlled vocabulary (`italian_restaurant`). `cuisine.py`
maps every raw label to a small canonical list and reconciles them per venue:

- `cuisine_tags` — sorted union of all canonical buckets across the platforms (a venue is
  typically multi-cuisine, e.g. `["Italian", "Pizza"]`).
- `cuisine_primary` — the single headline bucket: the most *specific* tag wins (`Pizza`
  beats umbrella `Italian`; `Chinese` beats `Asian`), ties broken by source precedence
  Tripadvisor > TheFork > Google.
- `cuisine_primary_source` — which platform the primary came from.
- `cuisine_n_sources` — how many platforms supplied a cuisine.
- `cuisine_agreement` — `single` / `agree` / `disagree` on the per-source primary bucket.

## Source Evidence

`sources.google` is always present. `sources.tripadvisor` and `sources.thefork` are
present only when a selected `entity_resolution_links` record points to an existing clean
source document.

Source blocks preserve native ids, URLs, source names/addresses/coordinates, raw platform
ratings, review counts, contacts, price evidence, cuisines or dietary options,
opening-hours/review samples where available, source flags, and match metadata for linked
non-Google sources.

Top-level `website` is the exact shared website when Google and Tripadvisor agree, or the
shared host when they only differ by URL path. When both sources disagree, Google is used
as the canonical value and all values stay in `website_evidence`.

Top-level `phones` is the de-duplicated list of all matched Google/Tripadvisor phone
values. No scalar top-level `phone` is emitted.

## Conflict-Handling Strategies per Top-Level Field

When two or more platforms describe the same canonical entity, each top-level field
applies one of the conflict-handling strategies from the Bleiholder & Naumann taxonomy
(ignoring / avoiding / resolution). The strategy is chosen per field according to whether
the value is authoritative (identity), comparative (ratings/counts), or reconcilable
(contacts/price).

| Top-level field(s) | Sources combined | Strategy | Classification | How we apply it |
|---|---|---|---|---|
| `canonical_name`, `canonical_address`, `canonical_*`, `latitude`, `longitude`, `coordinate_source` | google (preferred) | **Trust your friends** | avoiding, metadata based | Google is the geographic backbone and authoritative seed, so canonical identity/geography always takes Google's value. Source names/addresses/coords are preserved untouched under `sources.*`. |
| `google_rating_5`, `tripadvisor_rating_5`, `thefork_rating_5`, `thefork_rating_raw_10`, `google_review_count`, `tripadvisor_review_count`, `thefork_review_count` | google, tripadvisor, thefork | **Consider all possibilities** | ignoring | Ratings/counts are the comparison subject, so we deliberately do *not* resolve them — every source value is kept in its own column for the mandatory discrepancy queries. (TheFork's 0–10 scale is normalized to a parallel `_5` column for comparability.) |
| `rating_avg_5` | google, tripadvisor, thefork | **Meet in the middle** | resolution, instance based, mediating | Mean of the available `_5` ratings — a single mediated value that exists in no source. |
| `rating_range_5` | google, tripadvisor, thefork | **Meet in the middle** (dispersion) | resolution, instance based, mediating | Max − min of the `_5` ratings; a derived spread used to surface conflicts rather than hide them. |
| `website`, `website_source`, `website_match_status`, `website_evidence` | google, tripadvisor | **Take the information** + **Trust your friends** | avoiding, instance + metadata based | If only one source has a website we take it (prefer value over null). If both agree (exact or same host) we keep the shared value. On genuine disagreement we fall back to Google (preferred source); all raw values stay in `website_evidence`. |
| `phones`, `phone_match_status`, `phone_evidence` | google, tripadvisor | **Consider all possibilities** | ignoring | We keep the de-duplicated union of every matched phone value rather than picking one, since a venue legitimately has multiple lines. `phone_match_status` records whether sources agreed. |
| `price_level`, `price_level_source`, `price_evidence` | google, tripadvisor, thefork | **Cry with the wolves** | resolution, instance based, deciding | Each source's native price signal is mapped to a common 4-level label, then majority vote wins. A tie keeps the tied labels as a list (`price_level_source = "tie"`) — falling back to **consider all possibilities**. All raw signals stay in `price_evidence`. |
| `integration_flags`, `has_*`, `platform_count`, `rating_platform_count` | derived | — (provenance/aggregation) | n/a | Not conflict resolution: membership flags, counts, and audit flags (`multiple_*_matches`, `llm_override`, `missing_*_source_doc`) record how the integration was performed. |

Two strategies from the taxonomy are intentionally **not** used: *Pass it on* (escalate to a
user) has no place in a batch pipeline, and *Roll the dice* / *Keep up to date* are unsuitable
because source values lack reliable, comparable timestamps and a random pick would be
non-reproducible.

## Spark-Style `printSchema()`

MongoDB is schemaless, so this is the effective schema emitted by
`uv run dataman-unify` rather than a database-enforced contract. `sources.google` is
always present; `sources.tripadvisor` and `sources.thefork` are present only when a
resolved link exists.

```text
root
 |-- _id: string
 |-- integrated_restaurant_id: string
 |-- canonical_name: string
 |-- canonical_address: string
 |-- canonical_street: string
 |-- canonical_house_number: string
 |-- canonical_postal_code: string
 |-- canonical_city: string
 |-- latitude: double
 |-- longitude: double
 |-- coordinate_source: string
 |-- website: string
 |-- website_source: string
 |-- website_match_status: string
 |-- website_evidence: array<struct>
 |    |-- source: string
 |    |-- value: string
 |-- phones: array<string>
 |-- phone_match_status: string
 |-- phone_evidence: array<struct>
 |    |-- source: string
 |    |-- value: string
 |-- price_level: string|array<string>
 |-- price_level_source: string
 |-- price_evidence: array<struct>
 |    |-- source: string
 |    |-- level: string
 |    |-- raw: string|long
 |-- has_google: boolean
 |-- has_tripadvisor: boolean
 |-- has_thefork: boolean
 |-- has_all_three_platforms: boolean
 |-- platform_count: long
 |-- google_rating_5: double
 |-- tripadvisor_rating_5: double
 |-- thefork_rating_raw_10: double
 |-- thefork_rating_5: double
 |-- rating_platform_count: long
 |-- rating_avg_5: double
 |-- rating_range_5: double
 |-- google_review_count: long
 |-- tripadvisor_review_count: long
 |-- thefork_review_count: long
 |-- integration_flags: array<string>
 |-- _updated_at: timestamp
 |-- sources: struct
 |    |-- google: struct
 |    |    |-- ids: struct
 |    |    |    |-- _id: string
 |    |    |    |-- place_id: string
 |    |    |-- name: string
 |    |    |-- address: struct
 |    |    |    |-- address: string
 |    |    |    |-- street: string
 |    |    |    |-- house_number: string
 |    |    |    |-- postal_code: string
 |    |    |    |-- locality: string
 |    |    |    |-- province: string
 |    |    |    |-- country: string
 |    |    |    |-- city: string
 |    |    |-- coordinates: struct
 |    |    |    |-- latitude: double
 |    |    |    |-- longitude: double
 |    |    |    |-- coordinate_source: string
 |    |    |-- rating: struct
 |    |    |    |-- raw_5: double
 |    |    |    |-- rating_5: double
 |    |    |-- review_count: long
 |    |    |-- contacts: struct
 |    |    |    |-- website: string
 |    |    |    |-- phone: string
 |    |    |-- price: struct
 |    |    |    |-- price_level: string
 |    |    |    |-- price_range: struct
 |    |    |    |    |-- start: long
 |    |    |    |    |-- end: long
 |    |    |    |    |-- currency: string
 |    |    |-- classification: struct
 |    |    |    |-- primary_type: string
 |    |    |    |-- types: array<string>
 |    |    |    |-- category_tier: string
 |    |    |    |-- is_dining: boolean
 |    |    |    |-- business_status: string
 |    |    |    |-- is_operational: boolean
 |    |    |-- amenities: struct
 |    |    |    |-- dine_in: boolean
 |    |    |    |-- takeout: boolean
 |    |    |    |-- delivery: boolean
 |    |    |    |-- reservable: boolean
 |    |    |    |-- outdoor_seating: boolean
 |    |    |    |-- serves_* / good_for_* / other Google amenity flags: boolean
 |    |    |-- photo_count: long
 |    |    |-- reviews: array<struct>
 |    |    |    |-- author: string
 |    |    |    |-- language: string
 |    |    |    |-- publish_time: string
 |    |    |    |-- rating: long
 |    |    |    |-- text: string
 |    |    |-- flags: array<string>
 |    |-- tripadvisor: struct
 |    |    |-- ids: struct
 |    |    |    |-- _id: string
 |    |    |    |-- ta_location_id: string
 |    |    |    |-- source_url: string
 |    |    |-- name: string
 |    |    |-- address: struct
 |    |    |    |-- address: string
 |    |    |    |-- street: string
 |    |    |    |-- house_number: string
 |    |    |    |-- postal_code: string
 |    |    |    |-- city: string
 |    |    |-- coordinates: struct
 |    |    |    |-- latitude: double
 |    |    |    |-- longitude: double
 |    |    |    |-- has_coordinates: boolean
 |    |    |    |-- coordinate_source: string
 |    |    |-- rating: struct
 |    |    |    |-- raw_5: double
 |    |    |    |-- rating_5: double
 |    |    |-- review_count: long
 |    |    |-- contacts: struct
 |    |    |    |-- website: string
 |    |    |    |-- phone: string
 |    |    |    |-- email: string
 |    |    |-- price: struct
 |    |    |    |-- price_band: string
 |    |    |    |-- price_tier_level: long
 |    |    |-- cuisines: array<string>
 |    |    |-- opening_hours: array<struct>
 |    |    |    |-- day: string
 |    |    |    |-- opens: string
 |    |    |    |-- closes: string
 |    |    |-- reviews: array<struct>
 |    |    |    |-- nickname: string
 |    |    |    |-- contributions: long
 |    |    |    |-- title: string
 |    |    |    |-- text: string
 |    |    |    |-- date: string
 |    |    |-- sample_size: long
 |    |    |-- photo_count: long
 |    |    |-- flags: array<string>
 |    |    |-- match: struct
 |    |    |    |-- link_id: string
 |    |    |    |-- candidate_id: string
 |    |    |    |-- effective_label: string
 |    |    |    |-- label: string
 |    |    |    |-- llm_label: string
 |    |    |    |-- match_method: string
 |    |    |    |-- score: double
 |    |    |    |-- block_source: string
 |    |    |    |-- fast_path: string
 |    |    |    |-- components: struct
 |    |    |    |-- flags: array<string>
 |    |    |    |-- rejected_candidate_ids: array<string>
 |    |-- thefork: struct
 |    |    |-- ids: struct
 |    |    |    |-- _id: string
 |    |    |    |-- source: string
 |    |    |    |-- source_id: string
 |    |    |    |-- tf_id: string
 |    |    |    |-- restaurant_url: string
 |    |    |-- name: string
 |    |    |-- address: struct
 |    |    |-- coordinates: struct
 |    |    |    |-- latitude: double
 |    |    |    |-- longitude: double
 |    |    |    |-- coordinate_source: string
 |    |    |-- rating: struct
 |    |    |    |-- raw_10: double
 |    |    |    |-- rating_5: double
 |    |    |-- review_count: long
 |    |    |-- price: struct
 |    |    |    |-- avg_price_eur: long
 |    |    |    |-- discount_pct: long
 |    |    |    |-- has_discount: boolean
 |    |    |-- cuisines: array<string>
 |    |    |-- dietary_options: array<string>
 |    |    |-- opening_hours: array<struct>
 |    |    |-- review_snippets: array<string>
 |    |    |-- reviews: array<struct>
 |    |    |    |-- author_name: string
 |    |    |    |-- rating: double
 |    |    |    |-- text: string
 |    |    |    |-- date: string
 |    |    |-- sample_size: long
 |    |    |-- sample_avg_rating: double
 |    |    |-- rating_sample_divergent: boolean
 |    |    |-- scrape_provenance: struct
 |    |    |    |-- scraped_at: string
 |    |    |    |-- source_page_number: long
 |    |    |    |-- detail_scraped: boolean
 |    |    |-- flags: array<string>
 |    |    |-- match: struct
```
