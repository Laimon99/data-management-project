# Bicocca Data Management Project

## **Consistency and Quality of Online Restaurant Reviews in the Milan Area**

![Image](https://www.mapaplan.com/travel-map/milan-city-top-tourist-attractions-printable-street-plan-guide/high-resolution/milan-top-tourist-attractions-map-23-best-restaurants-dining-central-district-area-outline-layout-best-locations-visit-high-resolution.jpg)

![Image](https://images.squarespace-cdn.com/content/v1/5876d8d6e3df28c4d83ae377/1753791038525-ZICT8ERD8HT385S6MX4O/milan-milano-italy-brera-centro-storico-ip-03.jpg)

![Image](https://www.explore-italian-culture.com/images/osteria-di-brera-milan.jpg)

![Image](https://www.thetrainline.com/cms/media/5793/empty-seats-at-restaurant-in-milan-italy.jpg?height=440\&mode=crop\&quality=70\&width=660)

---


## 1️⃣ Domain & research questions

### Domain

Online restaurant review platforms provide ratings that strongly influence consumer behavior. However, ratings may differ across platforms due to **data quality issues**, **sampling bias**, or **integration errors**.

The project focuses on restaurants located in **Milan and surrounding municipalities**.

### Main research questions

> 1. **How consistent are restaurant ratings across different online platforms?**
> 2. **Which restaurants show the highest disagreement between platforms?**
> 3. **Is rating inconsistency related to data quality issues** (e.g. number of reviews, outdated information)?
> 4. **Can low-quality or sparse data inflate perceived restaurant quality?**

### Secondary questions

> * Are certain platforms systematically more optimistic/pessimistic?
> * Does inconsistency increase for smaller or less popular restaurants?
> * Does geographic location (center vs periphery) affect data completeness?

---


## 🛠 Setup

### Requirements

* Python 3.11+
* [`uv`](https://github.com/astral-sh/uv) package manager
* Any Chromium-based browser — Brave, Chrome, Edge, Vivaldi, Opera, or Chromium
  (optional, for the Tripadvisor scraper; falls back to Playwright's bundled
  Chromium if none is found)

### Install

```bash
uv sync --extra dev          # install runtime + dev dependencies
uv run pre-commit install    # (optional) install git hooks
uv run pytest                # run the test suite
```

### Configure API keys

```bash
printf "DATAMAN_GOOGLE_PLACES_API_KEY=your_key_here\n" > .env
```

The key must have **Places API (New)** enabled in Google Cloud
(*APIs & Services → Library → "Places API (New)" → Enable*) — the legacy
Places API will not work.

---


## 2️⃣ Data sources (FAQ 5 – acquisition)

### Source A — Google Maps / Google Places API

* **Type**: Official API via Places API (New)
* **Data**: see [`dataset-schema.md`](services/google_places_api_extract/dataset-schema.md)
* **Why**: high coverage in Milan, rich metadata, coordinates become the project geographic backbone
* **Tools**: Python + `httpx`, Tiled Nearby Search + Place Details, raw JSONL output in `data/raw/google_places/`

#### How the current seed dataset was collected

The dataset was built in three passes with a progressively smaller tile radius to fill gaps left by earlier runs. Results from all passes are deduplicated by `place_id` in the seed file.

| Pass | Tile radius | Area | Rationale |
|---|---|---|---|
| 1 | 750 m | Whole-city circle around Duomo | Broad initial sweep across the city |
| 2 | 300 m | Whole-city circle around Duomo | Finer tiling to recover venues missed by the coarser pass |
| 3 | 100 m | Dense neighbourhood anchors only | Fine-grained sweep in high-density zones where saturation was still uncertain |

#### Running

```bash
uv run google-places-api-extract list          # collect seed venues
uv run google-places-api-extract detail --all  # enrich every seed venue with full Place Details
```

Both runs are idempotent. See [`services/google_places_api_extract/README.md`](services/google_places_api_extract/README.md) for flags, env vars, neighbourhood anchors, and examples.

---

### Source B — Tripadvisor

* **Type**: Web scraping via Playwright
* **Data**:

  * Scraped restaurant name
  * Address
  * Rating
  * Review count
  * Optional review text / recency fields
* **Why**:

  * Different user base from Google
  * Useful for cross-platform rating consistency analysis

#### Running the Tripadvisor scraper

The scraper is packaged as `services/tripadvisor_scraper_extract`. Runtime files are
written under `data/raw/tripadvisor/`; the bundled restaurant URL list is copied
there on first run if no URL file exists yet. See
`docs/tripadvisor_scraper_extractor/tripadvisor-scraper-extract.md` for runtime
paths and browser setup details.

```bash
uv run tripadvisor-scraper-extract --order bottom
```

Use `--order bottom` when another teammate is scraping from the top of the URL
list. The default is `--order top`. The scraper auto-detects an installed
Chromium-based browser on macOS, Windows, and Linux, trying Brave, Chrome, Edge,
Vivaldi, Opera, and Chromium in that order; if none is found it falls back to
Playwright's bundled Chromium. Pass `--browser-path <path>` if your browser is
installed somewhere non-standard. (The old `--brave-path` flag still works as a
deprecated alias.)

---

### Source C — TheFork (planned)

* **Type**: Web scraping or another reproducible acquisition path
* **Data**:

  * Scraped restaurant name
  * Address
  * Rating
  * Review count
  * Optional booking/price metadata
* **Why**:

  * Restaurant-specific platform
  * Useful comparison against review-heavy general platforms

---


## 3️⃣ Data storage & modeling (FAQ 6)

### Current raw acquisition persistence

Downloaded/acquired data is treated as raw acquisition output and kept under
`data/raw/`.

**Google Places: `data/raw/google_places/`**

* `restaurants_seed.jsonl`: one JSON object per Google place
* `checkpoints/`: list/detail resume state
* seed records are deduplicated by `place_id` and include raw `details` after enrichment

**Tripadvisor: `data/raw/tripadvisor/`**

* `tripadvisor_list_restaurant.txt`: URL list
* `tripadvisor_scraper_results.json`: raw scraper output
* `tripadvisor_checkpoint.json`: scraper resume state
* `browser_automation_profile/`: persistent browser profile (cookies/session,
  kept so you don't have to re-solve CAPTCHAs on every run). It is git-ignored.
  Once you've finished scraping and no longer need the saved session, it is safe
  to delete this folder; the scraper just recreates a fresh profile on the next
  run. Only delete it while the scraper is **not** running.

Database/storage implementation for later stages is intentionally deferred. The
candidate DBMS architecture is documented in `docs/storage-design.md`, but it is
not part of the current Stage 1 scope.

### Future storage shape

**restaurants_raw_google**

* place_id
* name
* address
* lat, lon
* rating
* review_count
* types / primary_type
* raw details document

**restaurants_raw_tripadvisor**

* tripadvisor_id
* name
* address
* rating
* review_count
* raw scraped payload

**restaurants_raw_thefork**

* thefork_id
* name
* address
* rating
* review_count
* raw scraped payload

**restaurants_integrated**

* unified_restaurant_id
* google_place_id
* tripadvisor_id
* thefork_id
* canonical_name
* canonical_address
* lat, lon
* google_rating
* tripadvisor_rating
* thefork_rating
* rating_difference
* data_quality_score

### Mandatory queries (examples)

* Restaurants with **rating difference > 1 star**
* Average rating per platform by area
* Correlation between review count and rating variance

---

## 4️⃣ Data profiling & quality assessment 

### Profiling before integration

For each source:

* **Completeness**:

  * % missing addresses
  * % missing coordinates
* **Consistency**:

  * Rating ranges
* **Timeliness** (if available):

  * Last review date

### Profiling after integration

* % restaurants matched successfully
* % ambiguous matches
* % unmatched records

### Data quality dimensions used

* Completeness
* Consistency
* Accuracy (proxy via cross-platform agreement)
* Timeliness
* Uniqueness (duplicates)

---

## 5️⃣ Data integration & enrichment

### Core challenge: entity matching (record linkage)

Restaurants do **not share IDs** → you must resolve them.

### Matching strategy (automated)

1. **Blocking**:

   * Same city
   * Distance < 200 meters
2. **Similarity metrics**:

   * Name similarity (Levenshtein / Jaro-Winkler)
   * Address similarity
3. **Composite matching score**
4. **Threshold-based decision**:

   * Match
   * No match
   * Uncertain

### Measuring integration errors

* False matches
* Missed matches
* Ambiguous matches


---

## 6️⃣ Data quality improvement

Concrete, visible improvements:

* Remove duplicates
* Normalize restaurant names
* Address standardization
* Filter restaurants with too few reviews
* Weighted ratings based on review count

We can show **before vs after**:

* Rating variance
* Number of extreme outliers

---

## 7️⃣ Analysis & results

### Analyses you can present

* Distribution of rating differences
* Platform bias comparison
* Rating stability vs review volume
* Spatial visualization of inconsistent restaurants

### Example insights (expected)

* Restaurants with <20 reviews show higher variance
* One platform may be systematically more conservative than another
* Peripheral areas have lower data completeness
