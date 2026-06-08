# Schema Matching Correspondences

Status: correspondence investigation for the integration stage.

> **See also — [`schema-matching.md`](./schema-matching.md)** is the course-aligned formal
> rewrite and is **authoritative on relation/conflict classification**. This document
> remains the engineering reference and still carries the *Proposed Integrated Schema
> Starting Point* (the next stage). Where they differ, the formal doc corrects: rating
> 0–10 vs 1–5, the price representations, and the coordinate sources are **equivalences
> with conflicts (scaling / homonym / provenance), not disjunctions**; Google `types`
> vs `cuisines` is an **overlap** (the `*_restaurant` tokens are extractable cuisine),
> not a clean disjunction; and `Disjunction` is reserved for genuinely *confusable* pairs.

This document matches the three cleaned source schemas that feed entity resolution and
the future `restaurants_integrated` dataset:

- Google: [`restaurants_clean_google`](../services/transform/google_clean/clean-dataset-schema.md)
- Tripadvisor: [`restaurants_clean_tripadvisor`](../services/transform/tripadvisor_clean/clean-dataset-schema.md)
- TheFork: [`restaurants_clean_thefork`](../services/transform/thefork_clean/clean-dataset-schema.md)

The goal is not to collapse all fields into one flat schema immediately. The goal is to
make the semantic correspondences explicit so that later entity resolution, integrated
schema design, and mapping-rule generation can be done without guessing what similarly
named fields mean.

## Relation Types

| Relation | Meaning | Integration consequence |
|---|---|---|
| Equivalence | Fields describe the same real-world property at the same grain, allowing renaming, type normalization, or light unit conversion. | Can feed the same integrated attribute or source-specific platform columns. |
| IS-A | A field is a subtype, specialization, evidence item, or source-specific representation of a broader concept. | Keep the source field, but map it under a broader integrated concept. |
| Disjunction | Fields look related but measure different facts, use incompatible domains, or have unsafe semantics for direct merging. | Do not merge directly; keep separate or transform through an explicit rule. |

## Source Roles

| Source | Schema role | Integration note |
|---|---|---|
| Google | Seed and geographic backbone. Highest coverage, stable `place_id`, native coordinates, rich type/service metadata. | Use as canonical geography after a match. Filter with `is_dining`, `category_tier`, `is_operational`, and related flags before final analysis. |
| Tripadvisor | Independent review platform. Stable URL/location id, strong review coverage, contacts, cuisine/hours, no native coordinates. | Requires geocoded coordinates for proximity blocking. Current audited clean collection was produced with `--skip-geocode`, so coordinate coverage is 0 until the full geocode pass is run. |
| TheFork | Booking/review platform. Stable source id, native coordinates, 0-10 rating scale, strong cuisine/price/review snippet coverage. | Rating scale must be harmonized before cross-platform rating comparison. Native coordinates are useful matching evidence but should not replace Google as the final coordinate authority when a Google match exists. |

## High-Level Matching Summary

| Concept | Relation | Google | Tripadvisor | TheFork | Integration use |
|---|---|---|---|---|---|
| Source record key | IS-A | `_id` | `_id` | `_id` | Per-collection Mongo upsert key. Values are not comparable across sources. |
| Platform venue id | IS-A | `place_id` | `ta_location_id` | `tf_id` | Stable per-platform venue ids for audit, source membership, and mapping rules. |
| Source natural key | IS-A | `place_id` | `source_url` | `source_id` | Loader/upsert natural key. Do not join across platforms with these values. |
| Source URL | Equivalence | none in clean schema | `source_url` | `restaurant_url` | Platform detail URL. Google can expose a URL only if added later from raw/details or derived externally. |
| Display name | Equivalence | `name` | `restaurant_name` | `restaurant_name` | Primary name similarity field and display candidate. |
| Full address | Equivalence | `address` | `address` | `address` | Primary address similarity field and display candidate. |
| Street text | Equivalence, partial | `street` | `street` | `street` | Blocking and address similarity. Tripadvisor `street` may be less structured than Google/TheFork. |
| Civic number | IS-A | `street_number` | embedded in `street`/`address` | `house_number` | Address matching evidence. Extract from Tripadvisor if needed; do not assume `street` is civic-number-free. |
| Postal code | Equivalence | `postal_code` | `postal_code` | `postal_code` | Strong blocking evidence for Milan-area records. |
| City | Equivalence | `city` | `city` | `city` | Blocking, scope checks, and area-level analysis after canonicalization. |
| Coordinates | Equivalence with provenance caveat | `latitude`, `longitude` | `latitude`, `longitude` | `latitude`, `longitude` | Matching evidence. Final canonical coordinates should prefer Google after a Google match. |
| Aggregate rating | Equivalence after scale handling | `rating` on 1-5 | `rating` on 1-5 | `rating` on 0-10 | Keep raw source ratings and derive normalized 0-5 values for comparison. |
| Aggregate review count | Equivalence | `review_count` | `total_review` | `review_count` | Core quality/weighting field. |
| Low-review flag | Equivalence | `low_review` | `low_review` | `low_review` | Source-specific quality flag; threshold must be kept consistent or documented. |
| Rating availability | Equivalence | `has_rating` | `has_rating` | `has_rating` | Completeness metric. |
| Review-count availability | Equivalence, derived for Google | derive from `review_count is not null` | `has_review_count` | `has_review_count` | Completeness metric. Google does not currently store the explicit flag. |
| Photos | Equivalence | `photo_count` | `photo_count` | `photo_count` | Source richness evidence, not a restaurant-quality metric by itself. |
| Website | Equivalence | `website` | `website` | none in clean schema | High-confidence matching evidence when normalized. |
| Phone | Equivalence | `phone` | `phone_number` | none in clean schema | High-confidence matching evidence when normalized. |
| Email | IS-A contact evidence | none | `email` | none in clean schema | Tripadvisor-only enrichment; useful for audit, not cross-platform comparison. |
| Opening hours | Equivalence for available sources | none in clean schema | `opening_hours` | `opening_hours` | Optional matching/quality evidence. Google clean schema currently omits hours. |
| Review sample | Equivalence with nested-shape differences | `reviews` | `reviews` | `reviews` | Keep per-source arrays; do not merge into one undifferentiated review list. |
| Review sample size | Equivalence, derived for Google | derive as `len(reviews)` | `sample_size` | `sample_size` | Sample coverage metric; not the same as aggregate review count. |
| Cuisine vocabulary | Equivalence for Tripadvisor/TheFork | none | `cuisines` | `cuisines` | Merge as source-tag evidence; do not treat Google `types` as cuisine. |
| Dietary options | IS-A cuisine/service attribute | `serves_vegetarian_food` | none | `dietary_options` | Partial overlap only. TheFork has richer dietary taxonomy. |
| Price evidence | IS-A price concept | `price_level`, `price_range` | `price_band`, `price_tier_level` | `avg_price_eur` | Keep source-specific price fields; derive comparable price metrics only through explicit rules. |
| Promotions | IS-A offer attribute | none | none | `discount_pct`, `has_discount` | TheFork-only booking/commercial feature. |
| Source classification | IS-A source taxonomy | `primary_type`, `types`, `category_tier`, `is_dining` | `cuisines` | `cuisines`, `dietary_options` | Google taxonomy classifies place type; Tripadvisor/TheFork mostly classify food style. |
| Operational state | IS-A quality/scope status | `business_status`, `is_operational` | none | none | Google-only scope filter. |
| Quality flags | Equivalence of container, source-specific vocabulary | `flags` | `flags` | `flags` | Keep as per-source reason lists; do not union without prefixing source. |
| Transform metadata | Equivalence | `_transformed_at`, `_source_collection` | `_transformed_at`, `_source_collection` | `_transformed_at`, `_source_collection` | Lineage metadata for clean-layer reproducibility. |
| Scrape provenance | IS-A source lineage | none in clean schema | none in clean schema | `scraped_at`, `source_page_number`, `detail_scraped` | TheFork-only clean provenance; source-level audit field. |

## Identity Correspondences

| Canonical concept | Relation | Source fields | Notes |
|---|---|---|---|
| `source_record_id` | IS-A | Google `_id`; Tripadvisor `_id`; TheFork `_id` | Mongo document keys created from each source natural key. Equal names do not imply cross-source equality. |
| `source_venue_id` | IS-A | Google `place_id`; Tripadvisor `ta_location_id`; TheFork `tf_id` | Stable venue identifiers inside each platform. Preserve all three in the integrated dataset. |
| `source_natural_key` | IS-A | Google `place_id`; Tripadvisor `source_url`; TheFork `source_id` | The natural key used by the load/transform layer for idempotent upserts. |
| `source_url` | Equivalence | Tripadvisor `source_url`; TheFork `restaurant_url` | Both are restaurant detail URLs. Google clean schema has no equivalent field. |
| `source_name` | IS-A | TheFork `source` | TheFork stores the source label explicitly. Google/Tripadvisor source labels can be assigned by collection name. |

Integration decision: generate a new `integrated_restaurant_id` after entity resolution.
Never attempt to reuse one source id as the integrated id unless the integrated table is
explicitly Google-seeded and every row is guaranteed to have a Google match.

## Name, Address, And Geography

| Canonical concept | Relation | Google | Tripadvisor | TheFork | Notes |
|---|---|---|---|---|---|
| `name` | Equivalence | `name` | `restaurant_name` | `restaurant_name` | Normalized display names. Use for similarity, not as a unique key. |
| `address` | Equivalence | `address` | `address` | `address` | Full normalized address. Strong evidence but formatting still differs by source. |
| `street` | Equivalence, partial | `street` | `street` | `street` | Google and TheFork are closer to route/street name; Tripadvisor is parsed from full address before CAP and may include extra tokens. |
| `house_number` | IS-A | `street_number` | derive from `address` or `street` if needed | `house_number` | Standardize name to `house_number` in the integrated schema. |
| `postal_code` | Equivalence | `postal_code` | `postal_code` | `postal_code` | High-value blocking field in Italy because CAP has stable 5-digit format. |
| `city` | Equivalence | `city` | `city` | `city` | All transforms normalize `Milan` to `Milano` where applicable. |
| `locality` | IS-A geography component | `locality` | none | none | Google-only raw locality before canonical city fallback. Keep only as Google evidence. |
| `province` | IS-A geography component | `province` | none | none | Google-only administrative-area component, usually `MI`. |
| `country` | IS-A geography component | `country` | none | none | Google-only country component. |
| `latitude` | Equivalence with provenance | `latitude` | `latitude` | `latitude` | Same coordinate concept, different authority. |
| `longitude` | Equivalence with provenance | `longitude` | `longitude` | `longitude` | Same coordinate concept, different authority. |
| `has_coordinates` | Equivalence, derived for Google/TheFork | derive | `has_coordinates` | derive | Useful completeness metric; only Tripadvisor stores the explicit flag. |
| `city_out_of_area` | IS-A geography quality flag | `city_out_of_area` | none | none | Google-only scope flag; do not confuse with city value. |

Coordinate rule: use Google coordinates as final coordinates when the integrated record
is matched to Google. Use TheFork and geocoded Tripadvisor coordinates for blocking,
distance diagnostics, and unmatched-source handling. Do not average coordinates across
sources unless a later analysis explicitly needs a consensus point.

## Ratings And Review Counts

| Canonical concept | Relation | Google | Tripadvisor | TheFork | Notes |
|---|---|---|---|---|---|
| `rating_raw` | Equivalence of concept, disjoint scale for TheFork | `rating` 1-5 | `rating` 1-5 | `rating` 0-10 | Store raw values with source-specific columns. |
| `rating_5` | Equivalence after mapping | `rating` | `rating` | `rating / 2` | Required for rating-difference queries. Preserve raw TheFork value too. |
| `review_count` | Equivalence | `review_count` | `total_review` | `review_count` | Platform aggregate review count. |
| `has_rating` | Equivalence | `has_rating` | `has_rating` | `has_rating` | Completeness flag. |
| `has_review_count` | Equivalence, derived for Google | derive from `review_count` | `has_review_count` | `has_review_count` | Completeness flag. |
| `low_review` | Equivalence | `low_review` | `low_review` | `low_review` | Count-only quality signal. |
| `sample_avg_rating` | IS-A sample quality metric | none | none | `sample_avg_rating` | TheFork-only mean over retained nested reviews. Not an aggregate platform rating. |
| `rating_sample_divergent` | IS-A source quality flag | none | none | `rating_sample_divergent` | TheFork-only disagreement between platform aggregate and retained sample average. |

Rating rule: cross-platform comparison must use normalized 0-5 fields. For example,
`thefork_rating_5 = thefork_rating_raw_10 / 2`. Raw ratings stay available for audit and
for explaining scale transformations.

## Price, Cuisine, And Restaurant Attributes

| Canonical concept | Relation | Google | Tripadvisor | TheFork | Notes |
|---|---|---|---|---|---|
| `price_signal` | IS-A | `price_level`, `price_range` | `price_band`, `price_tier_level` | `avg_price_eur` | Same broad domain, different representations. |
| `price_range_eur` | IS-A | `price_range.start`, `price_range.end`, `price_range.currency` | none | none | Google-only numeric range. |
| `price_tier` | IS-A | `price_level` | `price_tier_level` | derive from `avg_price_eur` only if thresholds are defined | Comparable only after explicit tier-mapping rules. |
| `avg_price_eur` | IS-A | derive from `price_range` midpoint only if wanted | none | `avg_price_eur` | TheFork gives direct average price; Google gives a range. |
| `cuisines` | Equivalence for Tripadvisor/TheFork | none | `cuisines` | `cuisines` | Source vocabulary should be normalized later if used analytically. |
| `dietary_options` | IS-A | `serves_vegetarian_food` partially | none | `dietary_options` | Only vegetarian overlaps directly. Vegan, gluten-free, halal, kosher, and organic are TheFork-only unless added from another source. |
| `platform_types` | IS-A | `primary_type`, `types` | none | none | Google place taxonomy, not cuisine. |
| `category_tier` | IS-A dining scope classification | `category_tier` | none | none | Google-specific relevance tier. |
| `is_dining` | IS-A dining scope classification | `is_dining` | none | none | Google-specific boolean used to exclude non-dining noise. |
| `service_flags` | IS-A | Google service/amenity booleans | none | limited overlap through `dietary_options` | Google-only details such as `takeout`, `delivery`, `reservable`, `outdoor_seating`, and meal/beverage flags. |
| `discount` | IS-A commercial offer | none | none | `discount_pct`, `has_discount` | TheFork-only promotion signal. |

Cuisine rule: merge Tripadvisor and TheFork cuisines only as source-tag evidence. Google
`types` may say `restaurant`, `cafe`, or `bar`, but this is a place taxonomy, not a
cuisine vocabulary such as `Italian`, `Japanese`, or `Seafood`.

Price rule: keep source-specific price evidence first. Later, derive comparable fields
only when the rule is explicit, for example `thefork_avg_price_eur`, `google_price_mid_eur`,
and `tripadvisor_price_tier`.

## Contacts, Hours, Reviews, And Richness

| Canonical concept | Relation | Google | Tripadvisor | TheFork | Notes |
|---|---|---|---|---|---|
| `website` | Equivalence | `website` | `website` | none | Strong match evidence after URL normalization. |
| `phone` | Equivalence | `phone` | `phone_number` | none | Strong match evidence after phone normalization. |
| `email` | IS-A | none | `email` | none | Tripadvisor-only contact field. |
| `opening_hours` | Equivalence for available sources | none | `opening_hours` | `opening_hours` | Shapes are both tidy `{day, opens, closes}` objects, with TheFork optionally adding `closes_next_day`. |
| `has_hours` | Equivalence for available sources | none | `has_hours` | `has_hours` | Completeness flag for structured hours. |
| `photo_count` | Equivalence | `photo_count` | `photo_count` | `photo_count` | Source-richness count. |
| `reviews` | Equivalence with nested-shape caveat | `reviews` | `reviews` | `reviews` | All are capped/recent samples, not complete review populations. |
| `review_snippets` | IS-A review evidence | none | none | `review_snippets` | TheFork short snippets are not the same field as slim structured `reviews`. |
| `sample_size` | Equivalence, derived for Google | derive `len(reviews)` | `sample_size` | `sample_size` | Number of retained sample reviews. |
| `has_reviews` | Equivalence, derived for Google | derive from `reviews` non-empty | `has_reviews` | `has_reviews` | Review-sample coverage flag. |
| `review_author` | IS-A nested review field | `reviews[].author` | `reviews[].nickname` | `reviews[].author_name` | Similar concept but incompatible nested shapes. |
| `review_rating` | IS-A nested review field | `reviews[].rating` | none | `reviews[].rating` | Google/TheFork only in the retained review sample. |
| `review_text` | Equivalence nested field | `reviews[].text` | `reviews[].text` | `reviews[].text` | Text samples are comparable as text, but collection methods differ. |
| `review_date` | Equivalence nested field | `reviews[].publish_time` | `reviews[].date` | `reviews[].date` | Normalize to a common timestamp/date field later. |

Review rule: keep review samples nested under each source. Do not concatenate samples
into a single `reviews` array unless every nested object carries a `source` field and the
analysis explicitly wants pooled text.

## Quality And Metadata

| Canonical concept | Relation | Google | Tripadvisor | TheFork | Notes |
|---|---|---|---|---|---|
| `quality_flags` | Equivalence of container, source-specific vocabulary | `flags` | `flags` | `flags` | Prefix or nest by source to avoid collisions in meanings. |
| `is_operational` | IS-A quality/scope flag | `is_operational` | none | none | Google-only operational filter. |
| `business_status` | IS-A quality/scope status | `business_status` | none | none | Google-only source status. |
| `name_is_geographic` | IS-A quality/scope flag | `name_is_geographic` | none | none | Google-only noisy-name flag. |
| `_transformed_at` | Equivalence | `_transformed_at` | `_transformed_at` | `_transformed_at` | Transform run timestamp, not scrape timestamp. |
| `_source_collection` | Equivalence | `_source_collection` | `_source_collection` | `_source_collection` | Clean-layer lineage. |
| `scraped_at` | IS-A acquisition lineage | none in clean schema | none in clean schema | `scraped_at` | TheFork-only clean field. |
| `source_page_number` | IS-A acquisition lineage | none | none | `source_page_number` | TheFork-only listing provenance. |
| `detail_scraped` | IS-A acquisition lineage | none | none | `detail_scraped` | TheFork detail-enrichment provenance. |

Quality rule: source-specific flags should remain source-specific in the integrated
schema, for example `google_flags`, `tripadvisor_flags`, and `thefork_flags`. A derived
top-level `integration_flags` can then summarize cross-source issues such as
`rating_scale_normalized`, `missing_tripadvisor`, `ambiguous_match`, or
`coordinate_disagreement`.

## Merge Hazards: Disjunctions, Scaling, And Representation Conflicts

> Note: this table mixes two different things that the formal rewrite separates. Rows like
> the rating scale, the price representations, and the coordinate sources are **not
> disjunctions** — they are *equivalent concepts* carrying a **conflict** (scaling,
> homonym/structural, or provenance) and are merged after resolving that conflict. True
> **disjunctions** (confusable pairs that must never be equated — source ids, sample vs
> aggregate counts/ratings, snippets vs reviews) are catalogued precisely in
> [`schema-matching.md` §8](./schema-matching.md#8-disjointness-catalog-confusable-pairs-only).

| Fields | Why disjoint or unsafe | Resolution |
|---|---|---|
| TheFork `rating` vs Google/Tripadvisor `rating` | Same column name and concept, but TheFork uses 0-10 while Google/Tripadvisor use 1-5. | Store `thefork_rating_raw_10`; derive `thefork_rating_5 = rating / 2`. |
| `review_count` / `total_review` vs `sample_size` | Aggregate platform population count vs count of retained nested review samples. | Keep as separate concepts. |
| Platform `rating` vs TheFork `sample_avg_rating` | Platform aggregate rating vs average of recent retained review sample. | Use `sample_avg_rating` only as quality/evidence field. |
| TheFork `review_snippets` vs structured `reviews` | Snippets are short source-richness text fragments; `reviews` are slimmed review objects. | Keep separate or convert snippets into source-tagged text evidence with no rating/date assumptions. |
| Google `types` / `primary_type` vs Tripadvisor/TheFork `cuisines` | Google place taxonomy is not a cuisine taxonomy. | Use Google taxonomy for dining relevance; use Tripadvisor/TheFork for cuisine analysis. |
| Google `is_dining` vs Tripadvisor/TheFork records | Google explicitly flags dining relevance; the other clean schemas assume restaurant pages from restaurant platforms. | Use `is_dining` to filter Google candidates, not as a cross-source field. |
| Google `business_status` / `is_operational` vs source absence | Missing counterpart does not mean Tripadvisor/TheFork venue is non-operational or operational. | Treat as Google-only operational evidence. |
| Google coordinates vs TheFork native coordinates vs Tripadvisor geocoded coordinates | Same coordinate concept but different authority and generation method. | Use for distance evidence; choose canonical coordinate by rule, preferably Google when matched. |
| Google `price_range`, Google `price_level`, Tripadvisor `price_band`, Tripadvisor `price_tier_level`, TheFork `avg_price_eur` | Different units and domains: range object, categorical enum, euro-symbol band, ordinal tier, average price. | Keep source-specific price fields; derive comparable price features only with documented thresholds. |
| TheFork `has_discount` vs `discount_pct` | Presence of any discount text vs successful parse of a clean percentage. | Keep both if promotions are analyzed. |
| `_transformed_at` vs TheFork `scraped_at` | Transformation timestamp vs acquisition timestamp. | Preserve separately as lineage fields. |
| `flags` across sources | All are reason lists, but vocabularies differ. `low_review` exists across all; others are source-specific. | Nest or prefix flags by source; derive global flags separately. |
| Source ids across platforms | `place_id`, `ta_location_id`, and `tf_id` are all stable ids, but from disjoint namespaces. | Store all; never compare for equality across sources. |

## Proposed Integrated Schema Starting Point

This is a target shape for the next schema-integration step. It is intentionally
integration-oriented, not a replacement for the clean source collections.

### Entity Core

| Integrated field | Type | Source mapping rule |
|---|---|---|
| `integrated_restaurant_id` | str | New id created after entity resolution. |
| `canonical_name` | str | Prefer Google `name` when Google matched; otherwise best available matched source name. |
| `canonical_address` | str | Prefer Google `address` when Google matched; otherwise best available matched source address. |
| `canonical_street` | str or null | Prefer Google `street`; fallback TheFork `street`; fallback parsed Tripadvisor `street`. |
| `canonical_house_number` | str or null | Prefer Google `street_number`; fallback TheFork `house_number`; optionally parse Tripadvisor address. |
| `canonical_postal_code` | str or null | Prefer Google `postal_code`; fallback agreed source value. |
| `canonical_city` | str or null | Prefer Google `city`; fallback agreed source value. |
| `latitude` | float or null | Prefer Google `latitude`; fallback TheFork native coordinate; fallback Tripadvisor geocoded coordinate. |
| `longitude` | float or null | Same rule as `latitude`. |
| `coordinate_source` | str | `google`, `thefork`, `tripadvisor_geocoded`, or `none`. |

### Source Membership And Match Provenance

| Integrated field | Type | Source mapping rule |
|---|---|---|
| `google_place_id` | str or null | Google `place_id`. |
| `tripadvisor_location_id` | str or null | Tripadvisor `ta_location_id`. |
| `tripadvisor_source_url` | str or null | Tripadvisor `source_url`. |
| `thefork_id` | str or null | TheFork `tf_id`. |
| `thefork_source_id` | str or null | TheFork `source_id`. |
| `thefork_restaurant_url` | str or null | TheFork `restaurant_url`. |
| `match_status` | str | `match`, `no_match`, or `uncertain` from entity resolution. |
| `match_confidence` | float or null | Composite/entity-resolution confidence if produced. |
| `match_method` | str or null | Rule, model, LLM tie-break, or manual audit label. |
| `match_flags` | list[str] | Ambiguity, distance disagreement, weak name match, duplicate candidates, etc. |

### Ratings And Counts

| Integrated field | Type | Source mapping rule |
|---|---|---|
| `google_rating_raw_5` | float or null | Google `rating`. |
| `tripadvisor_rating_raw_5` | float or null | Tripadvisor `rating`. |
| `thefork_rating_raw_10` | float or null | TheFork `rating`. |
| `google_rating_5` | float or null | Same as Google raw rating. |
| `tripadvisor_rating_5` | float or null | Same as Tripadvisor raw rating. |
| `thefork_rating_5` | float or null | TheFork `rating / 2`. |
| `google_review_count` | int or null | Google `review_count`. |
| `tripadvisor_review_count` | int or null | Tripadvisor `total_review`. |
| `thefork_review_count` | int or null | TheFork `review_count`. |
| `rating_range_5` | float or null | Max minus min over available normalized platform ratings. |
| `rating_avg_5` | float or null | Mean over available normalized platform ratings. |
| `rating_platform_count` | int | Number of available normalized platform ratings. |

### Quality, Coverage, And Source Evidence

| Integrated field | Type | Source mapping rule |
|---|---|---|
| `google_low_review` | bool or null | Google `low_review`. |
| `tripadvisor_low_review` | bool or null | Tripadvisor `low_review`. |
| `thefork_low_review` | bool or null | TheFork `low_review`. |
| `google_flags` | list[str] | Google `flags`. |
| `tripadvisor_flags` | list[str] | Tripadvisor `flags`. |
| `thefork_flags` | list[str] | TheFork `flags`. |
| `integration_flags` | list[str] | Derived cross-source flags. |
| `has_google` | bool | Google match present. |
| `has_tripadvisor` | bool | Tripadvisor match present. |
| `has_thefork` | bool | TheFork match present. |
| `platform_count` | int | Count of matched platforms. |
| `has_all_three_platforms` | bool | True when Google, Tripadvisor, and TheFork are all matched. |

### Optional Enrichment Fields

| Integrated field | Type | Source mapping rule |
|---|---|---|
| `websites` | obj | Source-keyed websites from Google/Tripadvisor. |
| `phones` | obj | Source-keyed phones from Google/Tripadvisor. |
| `emails` | obj | Tripadvisor email if present. |
| `cuisines` | list[str] | Union of normalized Tripadvisor and TheFork `cuisines`, source-tagged if auditability is needed. |
| `dietary_options` | list[str] | TheFork `dietary_options` plus possible Google vegetarian flag mapped carefully. |
| `price_evidence` | obj | Source-keyed Google/Tripadvisor/TheFork price fields. |
| `opening_hours` | obj | Source-keyed Tripadvisor/TheFork hours, not a forced single truth. |
| `photo_counts` | obj | Source-keyed photo counts. |
| `review_samples` | obj | Source-keyed review arrays or counts. |

## Correspondence-Driven Entity Resolution Implications

The schema correspondences imply this matching order:

1. Block candidate pairs by coordinates when available. Google and TheFork have native
   coordinates; Tripadvisor requires a full geocode run for this to work well.
2. Use name, full address, street, postal code, and city as the primary similarity
   fields.
3. Use phone and website as high-confidence supporting evidence for Google vs
   Tripadvisor.
4. Use cuisine, price, hours, and review richness only as weak supporting evidence.
   They are too source-specific for hard joins.
5. Send only uncertain pairs to an LLM tie-breaker, with source ids, normalized names,
   addresses, distances, contacts, and relevant flags as context.

## Open Decisions For The Next Step

| Decision | Why it matters |
|---|---|
| Tripadvisor geocoding run | Without it, Tripadvisor cannot participate in proximity blocking except through postal code/address text. |
| Low-review threshold value | The `low_review` flags should be comparable only if the same threshold was used or the threshold is recorded. |
| Integrated storage shape | ClickHouse favors flat columns; Mongo favors nested source evidence. The proposed schema can support either, but mapping rules should choose one. |
| Treatment of non-Google-only restaurants | Decide whether the integrated dataset is strictly Google-seeded or whether TheFork/Tripadvisor-only entities are allowed. |
| Cuisine normalization vocabulary | Needed if cuisine becomes an analytical dimension rather than only matching evidence. |
| Area/neighborhood mapping | Needed for "average rating by area" and center-vs-periphery quality analysis. |

