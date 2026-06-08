# Schema Matching — Inter-Schema Correspondences

Status: **schemas-matching** stage of the generic integration framework.

```
 schemas ──► schemas transformation ──► SCHEMAS MATCHING ──► schemas integration ──► integrated schema
                  (clean transforms)     (this document)      (next: mapping rules)
```

This document is the *matching* deliverable: given the three **homogenized** source
schemas produced by the clean transforms, it makes the inter-schema correspondences
explicit so that the next stage (schemas integration + mapping-rule generation) can build
`restaurants_integrated` without guessing what similarly named fields mean.

It is a **course-aligned formal rewrite** of [`schema-correspondences.md`](./schema-correspondences.md).
The older document is kept as the engineering reference and still carries the *proposed
integrated-schema starting point* (which belongs to the next stage). Where the two
disagree, **this document is authoritative on relation/conflict classification**; the
substantive corrections are listed in [§9](#9-corrections-vs-the-previous-document).

Input schemas:

- Google — [`restaurants_clean_google`](../services/transform/google_clean/clean-dataset-schema.md) (10,786 docs)
- Tripadvisor — [`restaurants_clean_tripadvisor`](../services/transform/tripadvisor_clean/clean-dataset-schema.md) (7,539 docs)
- TheFork — [`restaurants_clean_thefork`](../services/transform/thefork_clean/clean-dataset-schema.md) (1,344 docs)

---

## 1. Method and vocabulary

Schema matching answers two separate questions, and the course framework keeps them
separate:

1. **What is the terminological relationship** between two schema elements (concept level)?
2. **What conflict** must integration resolve to actually merge them (representation level)?

A pair can be an *equivalence* and still carry a *conflict* — e.g. the rating attribute is
the **same concept** in all three sources (equivalence) but has a **scaling conflict**
(0–10 vs 1–5). Conflating "there is a conflict" with "the concepts are disjoint" is the
main imprecision this rewrite fixes.

### 1.1 Terminological relations (concept level)

| Relation | Symbol | Meaning | Integration consequence |
|---|---|---|---|
| **Equivalence** | `≡` | Same real-world property at the same granularity. | Feed one integrated attribute (possibly after resolving a conflict, §1.2). |
| **IS-A** | `⊑` | One element is a specialization / subset / piece of evidence for a broader concept. | Keep the source field; map it *under* the broader integrated concept. |
| **Overlap** | `⊓` | Vocabularies/extensions partially intersect; neither subsumes the other. | Split into the shared part (mergeable) and the source-specific part (kept separate). |
| **Disjointness** | `⊥` | The two elements denote **different facts** and must never be equated. | Keep strictly separate; equating them is an integration *error*. |

**Scoping rule for `⊥` (per project decision).** Disjointness is asserted **only between
*confusable* pairs** — fields that share a name, type, or obvious slot and could plausibly
be merged by a careless reader — yet measure different facts. Trivially unrelated pairs
(`rating` vs `address`) are not listed; the assertion would carry no information. A `⊥` row
therefore always answers: *"these look like the same thing, why must I not merge them?"*

### 1.2 Conflict taxonomy (representation level)

Following the classic schema-integration conflict classification:

| Conflict | Definition | Example in this project |
|---|---|---|
| **Naming — synonym** | Different attribute names, same concept. | `name` / `restaurant_name`; `review_count` / `total_review`; `phone` / `phone_number`; `street_number` / `house_number`. |
| **Naming — homonym** | Same attribute name, different concept or representation. | `rating` (1–5 vs 0–10); `price_range` (numeric object in Google vs euro-band string in TA vs raw price string in TheFork); `reviews` (different nested shapes). |
| **Scaling / unit** | Same concept, different scale or unit. | `rating` 0–10 (TheFork) vs 1–5 (Google, TA). |
| **Structural (incl. 1NF)** | Same concept modeled with a different structure or decomposition. | `address` (single string) vs decomposed `street`/`house_number`/`postal_code`/`city`; nested-review object shapes; coordinates present as attributes (Google/TheFork) vs absent and geocoded (TA). |
| **Semantic / granularity** | Same broad domain at different conceptual grain. | cuisine national vs regional (`Italiano` vs `Milanese`); `locality` vs canonical `city`; aggregate `rating` vs `sample_avg_rating`. |
| **Coverage** | One source lacks the concept entirely. | Google has no opening hours; TheFork clean has no website/phone/email. |

### 1.3 Schema level vs value level

Pure schema matching aligns **attributes and structure**. Several fields here carry their
own **controlled vocabulary inside the value** — `cuisines`, `dietary_options`, Google
`types`/`primary_type`. Aligning *those vocabularies* is **value-/instance-level**
heterogeneity, strictly a later step than schema matching, but it is surfaced in
[§7](#7-value-level-vocabulary-heterogeneity) because (a) it changes whether a field is
analytically joinable and (b) the user flagged these vocabularies as "a bit misaligned."
All figures in §7 are read from the live Mongo `restaurants_clean_*` collections.

### 1.4 Source roles

| Source | Role | Matching note |
|---|---|---|
| Google | Seed + geographic backbone; highest coverage, native coordinates, rich type/service metadata. | Canonical geography after a match; pre-filter with `is_dining` / `category_tier` / `is_operational`. |
| Tripadvisor | Independent review platform; stable URL/location id, strong reviews/contacts, **no native coordinates**. | Needs the geocode pass for proximity blocking (current clean run used `--skip-geocode`, coordinates 0%). |
| TheFork | Booking/review platform; native coordinates, **0–10** rating, strong cuisine/price/snippet coverage. | Rating must be rescaled before comparison; native coordinates are evidence but not the final authority when Google matches. |

---

## 2. Identity correspondences

| Integrated concept | Relation | Google | Tripadvisor | TheFork | Conflict | Note |
|---|---|---|---|---|---|---|
| `source_record_id` | `⊥` (confusable) | `_id` | `_id` | `_id` | — | All named `_id`; disjoint namespaces. Equal field name ≠ cross-source equality. |
| `source_venue_id` | `⊥` (confusable) | `place_id` | `ta_location_id` | `tf_id` | naming-synonym | All "stable venue id"; disjoint namespaces. Preserve all three; never join on them across sources. |
| `source_natural_key` | `⊑` | `place_id` | `source_url` | `source_id` | structural | Per-source upsert keys; each IS-A "natural key", not mutually comparable. |
| `source_detail_url` | `≡` | — (not in clean) | `source_url` | `restaurant_url` | naming-synonym | Restaurant detail URL. Google clean has none. |
| `source_label` | `⊑` | (collection name) | (collection name) | `source` | coverage | Only TheFork stores the label explicitly. |

> Integration decision (unchanged): mint a fresh `integrated_restaurant_id` after entity
> resolution; never reuse a source id as the integrated key unless every row is guaranteed
> to be Google-matched.

---

## 3. Name, address, and geography

| Integrated concept | Relation | Google | Tripadvisor | TheFork | Conflict | Note |
|---|---|---|---|---|---|---|
| `name` | `≡` | `name` | `restaurant_name` | `restaurant_name` | naming-synonym | Primary similarity field; not a key. |
| `address` | `≡` | `address` | `address` | `address` | structural | Full normalized line; formatting still differs by source. |
| `street` | `≡` | `street` | `street` | `street` | structural | Google/TheFork ≈ route name; TA is parsed from the full line before the CAP and may keep extra tokens. |
| `house_number` | `≡` | `street_number` | (embedded in `address`/`street`) | `house_number` | naming-synonym + structural | Standardize to `house_number`; parse out of TA if needed. |
| `postal_code` | `≡` | `postal_code` | `postal_code` | `postal_code` | — | High-value blocking key (Italian 5-digit CAP). |
| `city` | `≡` | `city` | `city` | `city` | semantic | All transforms fold `Milan → Milano`. |
| `locality` | `⊑` | `locality` | — | — | semantic-granularity | Google-only sub-city locality; IS-A the city concept. Keep as Google evidence. |
| `province` | `⊑` | `province` | — | — | coverage | Google-only admin area (usually `MI`). |
| `country` | `⊑` | `country` | — | — | coverage | Google-only. |
| `latitude` / `longitude` | `≡` (provenance differs) | native | geocoded | native | structural (source/accuracy) | Same concept, different **authority**: Google native, TheFork native, TA geocoded. Not a disjunction. |
| `has_coordinates` | `≡` (derive 2/3) | derive | `has_coordinates` | derive | coverage | Only TA stores the explicit flag. |
| `city_out_of_area` | `⊑` | `city_out_of_area` | — | — | coverage | Google-only scope flag; do not confuse with the `city` value. |

> **Coordinate authority rule:** prefer Google coordinates when matched; use TheFork
> native and TA geocoded coordinates for blocking, distance diagnostics, and
> unmatched-source handling. Do not average across sources unless an analysis explicitly
> wants a consensus point. This is an *equivalence + provenance* situation, **not** a
> disjunction.

---

## 4. Ratings and review counts

| Integrated concept | Relation | Google | Tripadvisor | TheFork | Conflict | Note |
|---|---|---|---|---|---|---|
| `rating` (concept) | `≡` | `rating` 1–5 | `rating` 1–5 | `rating` 0–10 | **scaling** | Same concept; resolve by rescaling, **not** by treating as disjoint. |
| `rating_5` (derived) | `≡` after rescale | `rating` | `rating` | `rating / 2` | scaling | Comparable field for the "difference > 1 star" query; keep raw values too. |
| `review_count` | `≡` | `review_count` | `total_review` | `review_count` | naming-synonym | Platform aggregate population count. |
| `has_rating` | `≡` | `has_rating` | `has_rating` | `has_rating` | — | Completeness flag. |
| `has_review_count` | `≡` (derive Google) | derive | `has_review_count` | `has_review_count` | coverage | Google does not store the explicit flag. |
| `low_review` | `≡` (threshold caveat) | `low_review` | `low_review` | `low_review` | semantic | Comparable only if the same `low_review_threshold` was used; record it. |
| `sample_avg_rating` | `⊥` (confusable) vs `rating` | — | — | `sample_avg_rating` | semantic | Mean over the *retained sample*, not the platform aggregate. On TheFork both are 0–10 → highly confusable. Quality signal only. |
| `rating_sample_divergent` | `⊑` | — | — | `rating_sample_divergent` | coverage | TheFork-only flag: aggregate vs sample disagreement. |

> **Rating rule:** the 0–10 vs 1–5 mismatch is a **scaling conflict on an equivalent
> attribute**. Store raw per-source ratings and a normalized `*_rating_5` for comparison
> (`thefork_rating_5 = thefork_rating / 2`).

---

## 5. Price, cuisine, classification, and attributes

| Integrated concept | Relation | Google | Tripadvisor | TheFork | Conflict | Note |
|---|---|---|---|---|---|---|
| `price` (concept) | `≡` | `price_level` + `price_range{start,end,currency}` | `price_band` + `price_tier_level` | `avg_price_eur` | **homonym + structural + scaling** | Same domain, four representations: categorical level, numeric range, euro-symbol band, ordinal tier, euro average. Equivalent concept; comparable only via documented tier/midpoint rules. **Not disjoint.** |
| `cuisines` | `≡` (concept) / `⊓` (vocabulary) | (extractable from `primary_type`, see §7) | `cuisines` | `cuisines` | semantic-granularity + value-vocab | Same concept; value vocabularies overlap but differ (§7). Merge as source-tagged evidence. |
| `dietary_options` | `⊑` | `serves_vegetarian_food` (vegetarian only) | — | `dietary_options` | coverage | Google contributes only the vegetarian tag; vegan/gluten_free/halal/kosher/organic are TheFork-only. |
| `platform_taxonomy` | `⊓` with `cuisines` | `primary_type`, `types`, `category_tier`, `is_dining` | — | — | semantic | Google place taxonomy; **partially overlaps** cuisine (`*_restaurant` tokens) but mostly venue-type. See §6 + §7. |
| `service_amenities` | `⊑` | service/amenity booleans (`takeout`, `delivery`, `reservable`, `outdoor_seating`, meal/beverage flags…) | — | (overlap via `dietary_options`) | coverage | Google-only rich attributes; missing means *unknown*, not false. |
| `discount` | `⊑` | — | — | `discount_pct`, `has_discount` | coverage | TheFork-only commercial offer. `has_discount` (presence) ⊑ `discount_pct` (parsed value) — keep both. |

> **Cuisine rule:** merge TA + TheFork `cuisines` as source-tagged evidence; for Google,
> derive cuisine from the `*_restaurant` `primary_type` tokens (§7) — do **not** treat the
> whole `types` list as cuisine. **Price rule:** keep source-specific price fields; derive
> comparable metrics only via explicit, documented rules.

---

## 6. Contacts, hours, reviews, richness

| Integrated concept | Relation | Google | Tripadvisor | TheFork | Conflict | Note |
|---|---|---|---|---|---|---|
| `website` | `≡` | `website` | `website` | — (deleted, 0%) | coverage | Strong match evidence after URL normalization. |
| `phone` | `≡` | `phone` | `phone_number` | — (deleted, 0%) | naming-synonym + coverage | Strong match evidence after phone normalization. |
| `email` | `⊑` | — | `email` | — | coverage | TA-only contact evidence. |
| `opening_hours` | `≡` | — (not in clean) | `opening_hours` | `opening_hours` | structural | Both tidy `{day, opens, closes}`; TheFork adds `closes_next_day`. |
| `has_hours` | `≡` (avail. sources) | — | `has_hours` | `has_hours` | coverage | Structured-hours completeness. |
| `photo_count` | `≡` | `photo_count` | `photo_count` | `photo_count` | — | Source-richness count, not a quality metric. |
| `reviews` (sample) | `≡` (concept) | `reviews` | `reviews` | `reviews` | **homonym + structural** | All are capped recent **samples**, not full populations; nested shapes differ (see below). |
| `review_snippets` | `⊥` (confusable) vs `reviews` | — | — | `review_snippets` | structural | Short text fragments with no rating/date; not the structured `reviews` objects. |
| `sample_size` | `≡` (derive Google) | derive `len(reviews)` | `sample_size` | `sample_size` | coverage | Count of *retained* reviews; see §8 disjointness vs `review_count`. |
| `has_reviews` | `≡` (derive Google) | derive | `has_reviews` | `has_reviews` | coverage | Review-sample coverage. |

Nested `reviews[]` shapes (structural conflict — same concept, incompatible structure):

| Nested concept | Google | Tripadvisor | TheFork | Relation / note |
|---|---|---|---|---|
| author | `author` | `nickname` | `author_name` | `≡` concept, naming-synonym |
| per-review rating | `rating` | — (absent) | `rating` | `⊑` (Google/TheFork only) |
| text | `text` | `text` | `text` | `≡` |
| date | `publish_time` | `date` | `date` | `≡`, naming-synonym + format conflict |

> **Review rule:** keep review samples nested **per source**. Pool into one array only if
> every object carries a `source` tag and the analysis explicitly wants pooled text.

---

## 7. Value-level vocabulary heterogeneity

This is **instance-level**, beyond pure schema matching, but decisive for whether
`cuisines`/`types` are analytically joinable. Figures are from the live Mongo collections.

### 7.1 `cuisines` — TheFork vs Tripadvisor

| | Tripadvisor | TheFork |
|---|---|---|
| Non-empty coverage | 5,859 / 7,539 (77.7%) | 1,319 / 1,344 (98.1%) |
| Distinct values | 56 | 63 |
| Form | feminine IT adjectives | masculine IT adjectives + regional |

Three distinct value-level conflicts, each mapped to a relation:

1. **Synonyms (gender/morphology), relation `≡`.** Same cuisine, different surface string:
   `Italiana` (TA, 4,044) ≡ `Italiano` (TF, 523); `Mediterranea` ≡ `Mediterraneo`;
   `Americana` ≡ `Americano`; `Asiatica` ≈ `Asiatico`/`Orientale`. (Some are
   gender-invariant and already identical: `Cinese`, `Giapponese`, `Libanese`.)
2. **Granularity / subsumption, relation `⊑`.** TheFork carries **regional Italian**
   cuisines that roll up under national Italian and have no TA counterpart:
   `Lombardo` (69), `Milanese` (56), `Romano`, `Siciliano`, `Pugliese`, `Toscano`,
   `Napoletano`, `Piemontese`, `Emiliano`, `Sardo`, `Campano` — all `⊑ Italiano`.
3. **Venue-type / cuisine blur, relation `⊓`.** `Pizza` (TA, 1,285) vs `Pizzeria`
   (TF, 164): one is a dish/cuisine token, the other a venue type. `Pesce` (TA) vs
   `Di Pesce` (TF) is a phrasing synonym.

### 7.2 Google `primary_type` — taxonomy that *partially* encodes cuisine

174 distinct values across 10,786 docs; it interleaves **venue type** and **cuisine**:

- Venue type (no cuisine): `bar` (2,111), `restaurant` (2,078), `coffee_shop` (577),
  `bakery` (539), `cafe` (271), `bistro` (254), `pub` (140), `wine_bar` (167).
- **Cuisine-bearing** (`*_restaurant`, extractable): `pizza_restaurant` (897),
  `italian_restaurant` (532), `chinese_restaurant` (200), `japanese_restaurant` (172),
  `seafood_restaurant` (125), `sushi_restaurant` (112), `korean_restaurant`,
  `indian_restaurant`, `american_restaurant`, `turkish_restaurant`,
  `peruvian_restaurant`, `hawaiian_restaurant`, …
- Non-dining noise: `hotel` (42), `supermarket` (40), `gas_station` (37), `store` (30).

So Google `types`/`primary_type` `⊓` `cuisines` (**overlap, not disjoint**): the
`*_restaurant` tokens map into the cuisine vocabulary (`italian_restaurant → Italian`),
while `bar`/`cafe`/`bakery` map into the venue/`category_tier` axis instead. The
already-derived `category_tier` (`restaurant` 5,816 / `cafe_bar_bakery` 4,624 /
`non_dining` 346) is a clean **3-way disjoint partition** over that venue axis.

### 7.3 `dietary_options` (TheFork) vs Google `serves_vegetarian_food`

TheFork tags (508 / 1,344 non-empty): `vegetarian` (474), `gluten_free` (177),
`vegan` (122), `organic` (31), `halal` (11), `kosher` (1). Only `vegetarian` `≡` Google
`serves_vegetarian_food`; the rest are TheFork-only (`⊑` a shared dietary concept).

### 7.4 Handling recommendation

- **Keep raw source vocab, source-tagged**, for audit (`cuisines_tripadvisor`,
  `cuisines_thefork`, `cuisines_google_derived`).
- **Build a small canonical cuisine vocabulary + per-source mapping table** doing two
  things: synonym normalization (`Italiana`/`Italiano`/`italian_restaurant → Italian`) and
  IS-A roll-up (`Milanese → Italian`, retaining the regional tag as a sub-attribute).
- **Priority:** cuisine is **weak** entity-resolution evidence and an **analytical
  dimension**, not a matching key — so vocabulary normalization is lower priority than
  rating rescaling and geo blocking, and should not block ER.

---

## 8. Disjointness catalog (confusable pairs only)

Per the §1.1 scoping rule, every entry is a pair that *looks* mergeable but must not be.

| Pair | Why confusable | Why disjoint | Resolution |
|---|---|---|---|
| `place_id` / `ta_location_id` / `tf_id` | All "stable venue id". | Disjoint id namespaces. | Store all three; never test equality across sources. |
| `_id` (×3) | Identical field name. | Per-collection Mongo keys from different natural keys. | Treat as source-local only. |
| `review_count`/`total_review` **vs** `sample_size` | Both "a count of reviews". | Aggregate population vs count of *retained* sample. | Separate fields; never substitute. |
| platform `rating` **vs** `sample_avg_rating` | Both "a rating number" (both 0–10 on TheFork). | Authoritative aggregate vs mean of retained sample. | `sample_avg_rating` is a quality signal only. |
| Google `types`/`primary_type` **vs** `cuisines` | Both look like "category/type". | Mostly different axes (venue vs cuisine) — but **partial overlap** on `*_restaurant`. | Treat as `⊓`: extract the cuisine subset; route the rest to `category_tier`. |
| TheFork `review_snippets` **vs** `reviews` | Both "review text". | Snippets carry no rating/date; `reviews` are structured objects. | Keep separate; if pooled, tag as snippet-only evidence. |
| `_transformed_at` **vs** `scraped_at` | Both timestamps. | Transform-run time vs acquisition time. | Preserve both as distinct lineage fields. |

Note the pairs deliberately **excluded** from this catalog because they are equivalences
with a conflict, not disjunctions: rating 0–10 vs 1–5 (scaling), the price representations
(homonym/structural), and the three coordinate sources (provenance).

---

## 9. Corrections vs the previous document

| Topic | `schema-correspondences.md` said | This document says |
|---|---|---|
| Rating 0–10 vs 1–5 | Listed under "Disjunctions And Unsafe Direct Merges". | **Equivalence + scaling conflict.** Disjunction is the wrong relation. |
| Price fields | Listed under disjunctions. | **Equivalence (one concept) + homonym/structural/scaling conflict.** |
| Coordinates | "Disjunction… same concept but different authority." | **Equivalence + provenance**, resolved by an authority rule, not a disjunction. |
| Google `types` vs `cuisines` | "Google place taxonomy is **not** a cuisine taxonomy" → disjoint. | **Overlap (`⊓`)**: `*_restaurant` tokens *are* extractable cuisine (data-grounded in §7.2). |
| Cuisine vocab | "Equivalence for TA/TheFork." | Equivalence of **concept** but **value-level misalignment** (synonyms + regional IS-A), documented in §7. |
| Disjunction scope | Used broadly for "do not merge / unsafe". | Reserved for **confusable** pairs only (§1.1). |

---

## 10. Implications for the next stage

- **Entity resolution order:** (1) block by coordinates (Google/TheFork native; TA needs
  the geocode pass); (2) similarity over `name`, `address`, `street`, `postal_code`,
  `city`; (3) `phone`/`website` as high-confidence support (Google↔TA); (4) cuisine, price,
  hours, richness as **weak** support only; (5) LLM tie-break for uncertain pairs.
- **Mapping rules to generate next** flow directly from the conflict column: rescale
  (`rating`), pick authority (coordinates), standardize names (`house_number`),
  derive-when-missing (`has_*`, `sample_size` for Google), source-tag-and-normalize
  (`cuisines`), keep-source-specific (price, flags, service amenities, provenance).
- The concrete target shape is the **proposed integrated schema** already drafted in
  [`schema-correspondences.md` §"Proposed Integrated Schema Starting Point"](./schema-correspondences.md#proposed-integrated-schema-starting-point);
  it is consistent with the relations above.

## 11. Open decisions

| Decision | Why it matters |
|---|---|
| Run the Tripadvisor geocode pass | Without coordinates, TA can only block on CAP/address text. |
| Pin one `low_review_threshold` across sources | `low_review` flags are comparable only with a shared (or recorded) threshold. |
| Canonical cuisine vocabulary | Needed only if cuisine becomes an analytical dimension (§7.4). |
| Google-seeded vs source-inclusive integrated set | Decides whether TA/TheFork-only venues get a row. |
| Area/neighborhood mapping | Needed for "average rating by area" and centre-vs-periphery analysis. |
