# Restaurant Ratings Integration Project

IMPORTANT!!!! THIS IS JUST ROUGH IDEA AND NOT MRD OR REAL IMPLEMENTATION PLAN. ESPECIALLY REGARDING THE ARCHITECTURE AND FLOW. THOSE ARE SUBJECTS TO CHANGE!!!!

## Project Overview

This project aims to **compare restaurant ratings across multiple online platforms** by building a unified dataset that integrates data scraped from:

* **Google Maps** (reference dataset and geographic seed)
* **Tripadvisor**
* **TheFork**

The core objective is to **analyze rating consistency and discrepancies** across platforms by resolving entity matching issues using **LLM-based semantic matching**, while also enabling **geographic analysis** through latitude and longitude coordinates.

---

## High-Level Architecture

```
Google Maps (seed + geo)
        │
        ▼
Restaurant List (name, address, lat, lon)
        │
        ├──► Tripadvisor Scraper
        ├──► TheFork Scraper
        │
        ▼
Platform-specific raw tables  (restaurants_raw_{google,tripadvisor,thefork})
        │
        ▼
Transform layer (clean / normalize / structure / flag)  — all three implemented
   • google_clean              → restaurants_clean_google        (uv run google-clean)
   • tripadvisor clean+geocode → restaurants_clean_tripadvisor   (uv run tripadvisor-clean)
   • thefork_clean             → restaurants_clean_thefork       (uv run thefork-clean)
        │
        ▼
Entity-resolution candidate generation
   • Google × Tripadvisor
   • Google × TheFork
   • writes entity_resolution_candidates        (uv run dataman-entity-resolve)
        │
        ▼
LLM/manual uncertain-pair resolution
   • reads entity_resolution_candidates
   • writes llm_label on candidate docs
        │
        ▼
Resolved links + integrated ratings collection
   • entity_resolution_links
   • restaurants_integrated / restaurants_ratings_final
```

> **Transform (T) layer — all three sources implemented.** Each source is cleaned
> Mongo→Mongo before matching; the raw collections stay immutable. All three share the
> same idioms: per-record quality `flags`/`has_*`, a `CleanReport`, full-run stale-delete
> convergence, and a source/destination collision guard.
> - **Google** — `services/transform/google_clean` (`uv run google-clean`): projects lean
>   fields out of the raw `details` blob, normalizes name/city, lifts structured address
>   parts, copies the authoritative coordinates (never re-geocoded), and classifies dining
>   relevance (`is_dining` / `category_tier`).
> - **Tripadvisor** — `services/transform/tripadvisor_clean` (`uv run tripadvisor-clean`):
>   type-repairs the Italian display strings, structures price/cuisine/hours/reviews,
>   lifts `ta_location_id`, and **geocodes** the cleaned address (Tripadvisor ships no
>   coordinates).
> - **TheFork** — `services/transform/thefork_clean` (`uv run thefork-clean`): parses the
>   1NF-violation fields (already typed and geocoded upstream, so no type-repair/geocoding).
>
> See each service's README + `eda-report.md`, and `specs/google-places-elt-transform.md` /
> `specs/thefork-elt-transform.md` / `specs/tripadvisor-clean-parity.md`.

---

## Step 1 – Restaurant List Acquisition (Seed)

### Why Google Maps

Google Maps is used as the **reference source** because it provides:

* the **most complete coverage** of restaurants
* consistent availability of **name + address**
* direct access to **geographic coordinates**
* a stable geographic scope (e.g. city-level search)

### Seed Collection Strategy

Restaurants are collected by performing **area-based searches** (e.g. by city zones or neighborhoods).
For each restaurant, the following attributes are extracted directly from the Google Maps page.

### Output

**`restaurants_seed`**

| restaurant_id | name | address | city | latitude | longitude |
| ------------- | ---- | ------- | ---- | -------- | --------- |

This table defines the **universe of restaurants** and serves as the **geographic backbone** of the project.

> Geographic coordinates are extracted directly during the seed scraping phase and are not obtained via external geocoding APIs.

---

## Step 2 – Web Scraping (Per Platform)

For each restaurant in `restaurants_seed`, targeted scraping is performed on:

### Google Maps

* rating
* number of reviews

### Tripadvisor

* rating (when available)
* number of reviews

### TheFork

* rating (when available)
* number of reviews

Each platform generates its **own table**, without assuming perfect name or address matching.

**Tables:**

* `google_maps_reviews`
* `tripadvisor_reviews`
* `thefork_reviews`

| platform_id | scraped_name | scraped_address | rating | review_count |
| ----------- | ------------ | --------------- | ------ | ------------ |

---

## Step 2b – Transform (Clean / Structure / Geocode / Flag)

Before entity resolution, raw per-platform records are transformed **Mongo → Mongo**
(the raw collections stay immutable). **All three transforms are implemented** and share
the same idioms — per-record `flags`/`has_*`, a `CleanReport` of before/after counts,
full-run stale-delete convergence, and a source/destination collision guard:

* **`google_clean`** (`uv run google-clean`) → `restaurants_clean_google`: projects lean
  fields out of the raw `details` blob, normalizes name/city, lifts structured address
  parts, copies the authoritative coordinates (**never** re-geocoded), and flags dining
  relevance (`is_dining` / `category_tier`).
* **`tripadvisor_clean`** (`uv run tripadvisor-clean`) → `restaurants_clean_tripadvisor`:
  type-repairs the Italian display strings (`"5,0" → 5.0`, `"(1.234 recensioni)" → 1234`,
  `"NaN"` → `null`), normalizes name/address/contacts, **structures** the 1NF-violation
  fields (`price_range` → tier, `cuisine_type` → `cuisines`, `working_days_hours` →
  `opening_hours`, `review` → slim capped `reviews`), lifts `ta_location_id`, and
  **geocodes** the cleaned address via Nominatim/OpenStreetMap as a sub-step (resumable;
  `--skip-geocode` for a fast clean-only pass) — Tripadvisor ships no coordinates.
* **`thefork_clean`** (`uv run thefork-clean`) → `restaurants_clean_thefork`: parses the
  1NF-violation fields (price/cuisine/discount/hours), normalizes name/city/address, lifts
  `tf_id`, and slims reviews. TheFork arrives already typed and geocoded, so there is no
  type-repair or geocoding.

Each returns a `CleanReport` feeding the Step-5 quality assessment. Geocoding (Tripadvisor
only) is part of that transform, **not** a separate stage.

---

## Step 3 – Entity Resolution Candidate Generation

Direct joins are **not reliable** because:

* restaurant names differ across platforms
* addresses may be abbreviated or formatted differently
* chains and branches introduce ambiguity

This creates a **classic entity resolution problem**, even when geographic proximity is
available. The current implemented service handles the first ER layer by generating
auditable candidate pairs before any LLM is used.

**Implemented service:**

```bash
uv run dataman-entity-resolve
```

**Input collections:**

* `restaurants_clean_google` — anchor pool, filtered to `is_dining=true` and
  `is_operational=true`.
* `restaurants_clean_tripadvisor`
* `restaurants_clean_thefork`

**Output collection:**

* `entity_resolution_candidates`

Google is always the anchor. The service generates two independent pair sets:

* Google × Tripadvisor
* Google × TheFork

Tripadvisor and TheFork are **not** matched directly. They are connected downstream only
through the shared Google `place_id`.

Each candidate document stores:

* `google_id`
* `source` (`tripadvisor` or `thefork`)
* `source_id`
* `block_source` (`geo`, `postal_code`, `fast_path`, `unblockable`)
* `score`
* `dmin` / `dmax` thresholds used for that candidate label
* `is_chain`, `chain_brand`, and `chain_hardening` for curated repeated brands
* `components` (`name_sim`, `geo_dist_m`, `street_sim`, contacts, postal match, etc.)
* provisional `label` (`MATCH`, `NON_MATCH`, `UNCERTAIN`, `UNBLOCKABLE`)
* `llm_label`, initially `null`

The command supports calibrated thresholds per source:

```bash
uv run dataman-entity-resolve \
  --dmin-tripadvisor 0.57 \
  --dmax-tripadvisor 0.62 \
  --dmin-thefork 0.68 \
  --dmax-thefork 0.90
```

Normal and chain venues can be calibrated separately. Chain thresholds are optional and
fall back to the source thresholds when omitted:

```bash
uv run dataman-entity-resolve \
  --dmin-tripadvisor 0.57 \
  --dmax-tripadvisor 0.62 \
  --dmin-thefork 0.68 \
  --dmax-thefork 0.90 \
  --dmin-chain-tripadvisor 0.65 \
  --dmax-chain-tripadvisor 0.85 \
  --dmin-chain-thefork 0.75 \
  --dmax-chain-thefork 0.92
```

For a clean full rewrite of the candidate collection:

```bash
uv run dataman-entity-resolve --replace-destination
```

By default reruns upsert candidate documents and preserve rows where `llm_label != null`.
`--replace-destination` is an explicit opt-in destructive rewrite.

Curated repeated chain brands use stricter branch matching: automatic `MATCH` labels are
capped to `UNCERTAIN` unless the pair is within the chain-specific distance threshold or
has an exact phone match. This protects branch-heavy names such as `La Piadineria`,
`McDonald's`, `Alice Pizza`, `Spontini`, `Burger King`, and `KFC`.

---

## Step 4 – LLM / Manual Resolution Of Uncertain Pairs

The LLM is **not** responsible for generating all possible matches from scratch. It reads
from `entity_resolution_candidates`, focuses on pairs that need adjudication, and writes
its decision back to the same candidate document.

### LLM Input

The LLM resolution step should read candidate documents where:

* `label == "UNCERTAIN"`, or
* a later audit rule explicitly requests review of borderline `MATCH` pairs.

The prompt/context should include:

* Google and source names
* address parts and postal code
* geographic distance
* phone/website evidence when available
* score components
* cuisine/price/hours only as weak contextual signals

### LLM Output

The LLM does not create new records. It updates the candidate document with:

* `llm_label = "MATCH"` or `"NON_MATCH"`
* optional audit metadata, if implemented later (`llm_model`, explanation, timestamp)

Final matching decision rule:

```text
effective_label = llm_label if llm_label is not null else label
```

LLMs are used **only for decision support**, not for data generation.

---

## Step 5 – Unified Dataset Construction

Candidate pairs are still not final restaurant records. The integration stage must first
collapse candidate pairs into resolved links, then populate the integrated collection.

### Step 5a – Resolved Link Selection

Read from:

* `entity_resolution_candidates`

Write to:

* `entity_resolution_links`

For each source independently:

* Google × Tripadvisor
* Google × TheFork

Select links where:

```text
effective_label == MATCH
```

Then enforce one-to-one assignment:

* one Google restaurant can have at most one Tripadvisor link
* one Google restaurant can have at most one TheFork link
* one Tripadvisor record can link to at most one Google restaurant
* one TheFork record can link to at most one Google restaurant

If multiple `MATCH` candidates compete, choose the best link using:

1. `llm_label == MATCH` over automatic-only `MATCH`
2. higher `score`
3. `fast_path` phone/website evidence
4. lower `components.geo_dist_m`
5. higher `components.name_sim`

Ambiguity should be retained as `integration_flags`, for example:

* `multiple_tripadvisor_matches`
* `multiple_thefork_matches`
* `source_record_matched_multiple_google`
* `llm_override`

### Step 5b – Integrated Restaurant Records

Read from:

* `restaurants_clean_google`
* `restaurants_clean_tripadvisor`
* `restaurants_clean_thefork`
* `entity_resolution_links`

Write to:

* `restaurants_integrated` (or final analytics alias `restaurants_ratings_final`)

The integrated collection is Google-seeded:

```text
one integrated record = one Google restaurant anchor
```

Tripadvisor and TheFork fields are attached only when a resolved link exists.

**`restaurants_integrated` / `restaurants_ratings_final`**

| restaurant_id | name | address | latitude | longitude | google_rating | tripadvisor_rating | thefork_rating |
| ------------- | ---- | ------- | -------- | --------- | ------------- | ------------------ | -------------- |

Core mapping rules:

* `restaurant_id` / `integrated_restaurant_id` is minted from the Google `place_id`.
* canonical `name`, address, `latitude`, and `longitude` come from Google.
* `google_rating_5` is Google `rating`.
* `tripadvisor_rating_5` is Tripadvisor `rating`.
* `thefork_rating_raw_10` is TheFork `rating`.
* `thefork_rating_5 = thefork_rating_raw_10 / 2`.
* source ids are preserved: `google_place_id`, `tripadvisor_location_id`, `thefork_id`.
* match evidence is preserved source-by-source from `entity_resolution_links`.
* unresolved `UNCERTAIN`, `NON_MATCH`, and `UNBLOCKABLE` candidates are not attached to
  the integrated record by default.

Derived analytics fields:

* `rating_platform_count`
* `rating_avg_5`
* `rating_range_5`
* `has_google`
* `has_tripadvisor`
* `has_thefork`
* `has_all_three_platforms`
* source-specific review counts
* source-specific quality flags

This table enables:

* cross-platform rating comparison
* statistical analysis of rating divergence
* geographic aggregation (zones, clusters, heatmaps)

---

## Exploratory Data Analysis (EDA)

Exploratory Data Analysis is performed on both **single-source** and **integrated datasets**.

### Single-source EDA

* rating distribution per platform
* distribution of number of reviews
* detection of outliers (very high / low ratings)

### Integrated EDA

* pairwise rating differences between platforms
* variance of ratings per restaurant
* correlation between rating and review count
* geographic visualization of average ratings (heatmaps)

EDA allows identifying **systematic differences** and **platform-specific behaviors**.

---

## Data Quality Assessment & Improvement

Data quality is evaluated and improved after integration.

### Selected Quality Dimensions

#### 1. Completeness

* percentage of missing ratings per platform
* restaurant coverage across platforms

**Improvement actions:**

* preservation of NULL values
* completeness-aware analysis

#### 2. Consistency

* rating divergence across platforms
* identification of conflicting evaluations

**Improvement actions:**

* exclusion of low-confidence matches
* normalization of restaurant identifiers

---

## Methodological Notes

* Google Maps is used **only as a seed and geographic reference**
* Platforms are treated as **independent sources**
* LLMs are used **exclusively for entity resolution**
* Coordinates are not re-geocoded
* Data quality is explicitly measured and improved

---

## Key Concepts Covered

* Web scraping
* Multi-source data integration
* Entity resolution with LLMs
* Exploratory Data Analysis
* Data quality assessment
* Geographic analysis

---

## Possible Extensions

* Geographic clustering of restaurants
* Weighting ratings by review count
* Hybrid rule-based + LLM matching
* Temporal analysis of reviews
