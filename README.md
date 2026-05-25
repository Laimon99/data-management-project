# data-management-project

---

## Project title (WIP)

**Consistency and Quality of Online Restaurant Reviews in the Milan Area**

![Image](https://www.mapaplan.com/travel-map/milan-city-top-tourist-attractions-printable-street-plan-guide/high-resolution/milan-top-tourist-attractions-map-23-best-restaurants-dining-central-district-area-outline-layout-best-locations-visit-high-resolution.jpg)

![Image](https://images.squarespace-cdn.com/content/v1/5876d8d6e3df28c4d83ae377/1753791038525-ZICT8ERD8HT385S6MX4O/milan-milano-italy-brera-centro-storico-ip-03.jpg)

![Image](https://www.explore-italian-culture.com/images/osteria-di-brera-milan.jpg)

![Image](https://www.thetrainline.com/cms/media/5793/empty-seats-at-restaurant-in-milan-italy.jpg?height=440\&mode=crop\&quality=70\&width=660)

---

## 🚀 Setup & Stage 1 (seed acquisition)

Stage 1 is a two-mode Google Places API (New) client that builds the
`restaurants_seed` collection — the geographic backbone of the project.

### Install

```bash
uv sync --extra dev          # install runtime + dev dependencies
uv run pre-commit install    # (optional) install git hooks
uv run pytest                # run the test suite (no API key needed)
```

### Configure the API key

```bash
cp .env.example .env
# edit .env and paste your key after DATAMAN_GOOGLE_PLACES_API_KEY=
```

The key must have **Places API (New)** enabled in Google Cloud
(*APIs & Services → Library → "Places API (New)" → Enable*) — the legacy
Places API will not work. `.env` is gitignored; the key is never written to
any log, file, or output document.

### Quick test — load ~10 venues from Milan centre

To make a single Nearby Search call around Piazza del Duomo, constrain the
search area so only one tile is generated, then cap the result count:

```bash
echo "DATAMAN_OUTER_RADIUS_M=500" >> .env       # one Duomo-centred tile
uv run pipeline-stage1 list --whole-city --max-results 10
```

`--whole-city` restricts the run to the single whole-city circle (Duomo +
`DATAMAN_OUTER_RADIUS_M`), which is what makes the radius override above produce
a single tile. Without it, the default run also tiles the dense neighbourhood
anchors (see below) and ignores `DATAMAN_OUTER_RADIUS_M` for those.

A JSON `ListReport` is printed to stdout (`tiles_processed`, `unique_places`,
`pages_fetched`, `errors`) and the venues land in `data/restaurants_seed.jsonl`.
Inspect them:

```bash
head data/restaurants_seed.jsonl | uv run python -c \
  "import sys, json; [print(json.loads(l)['name'], '—', json.loads(l)['formatted_address']) for l in sys.stdin]"
```

The run is idempotent: completed tiles are recorded in
`data/checkpoints/list_tiles.json` and skipped on re-run. Delete that file to
force a re-fetch.

### Enrich with full Place Details (Mode 2)

```bash
uv run pipeline-stage1 detail --all                 # enrich every seed venue
uv run pipeline-stage1 detail --place-id <PLACE_ID> # or a single venue
```

Mode 2 merges the full raw Place Details payload into each seed document,
preserving the seed fields. Already-enriched venues are tracked in
`data/checkpoints/detail_done.txt` and skipped on re-run.

> CLI forms are interchangeable: `pipeline-stage1 list` ≡
> `pipeline-stage1 --mode list`, and likewise for `detail`.

### Behaviour on errors

- Invalid key / bad request → `PermanentPlacesError` (4xx), not retried.
- Rate limit (429) or transient 5xx → retried up to 5× with exponential backoff.
- A venue that fails after retries is logged with its `place_id` and reason;
  the run continues rather than aborting.

### Full run (acceptance target ≥ 500 venues)

By default `list` gives **maximum coverage**: the whole-city circle (single
Duomo centre out to `DATAMAN_OUTER_RADIUS_M`, defaults to 9 km) **plus** a
curated set of high-density neighbourhood anchors (Navigli, Brera, Isola, Porta
Venezia/Romana, Corso Sempione, Loreto, ...). Tiles from every centre are merged
and deduplicated, so each area is queried at most once. Drop `--max-results` for
the full run:

```bash
uv run pipeline-stage1 list          # whole-city circle + all neighbourhood anchors
uv run pipeline-stage1 detail --all
```

Flags narrow the coverage (use at most one):

```bash
uv run pipeline-stage1 list --whole-city               # whole-city circle only
uv run pipeline-stage1 list --all-neighbourhoods       # all anchors only, no city circle
uv run pipeline-stage1 list --neighbourhood navigli_1  # a single named anchor
```

Override the anchors via `DATAMAN_NEIGHBOURHOODS` (JSON list of
`{name, lat, lon, outer_radius_m}`); set it to `[]` so the default run covers
only the whole-city circle.

---

## 1️⃣ Domain & research questions

### Domain

Online restaurant review platforms provide ratings that strongly influence consumer behavior. However, ratings may differ across platforms due to **data quality issues**, **sampling bias**, or **integration errors**.

The project focuses on restaurants located in **Milan and surrounding municipalities**.

### Main research questions

1. **How consistent are restaurant ratings across different online platforms?**
2. **Which restaurants show the highest disagreement between platforms?**
3. **Is rating inconsistency related to data quality issues** (e.g. number of reviews,, outdated information)?
4. **Can low-quality or sparse data inflate perceived restaurant quality?**

### Secondary questions

* Are certain platforms systematically more optimistic/pessimistic?
* Does inconsistency increase for smaller or less popular restaurants?
* Does geographic location (center vs periphery) affect data completeness?

---

## 2️⃣ Data sources (FAQ 5 – acquisition)

❗❗❗**UP FOR DEBATE** ❗❗❗

### Source A — Google Maps (scraping) - may be hard to scrape, but first source that comes to mind

* **Type**: Web scraping
* **Data**:

  * Restaurant name
  * Address
  * Coordinates (lat/lon)
  * Rating
  * Number of reviews
  * Category (Italian, pizza, sushi…)
* **Why**:

  * High coverage in Milan
  * Rich metadata
* **Tools**:

  * Selenium / Playwright
  * Requests + BeautifulSoup (for lightweight pages)

### Source B — Yelp Fusion API - ❗❗❗❗❗❗ PAID ❗❗❗❗❗❗

* **Type**: Official API
* **Data**:

  * Business name
  * Address
  * Rating
  * Review count
  * Price range
  * Categories
* **Why**:

  * Clean structured API
  * Different user base → meaningful comparison

### (Optional) Source C — TripAdvisor (scraping)

Used only if time allows, as an **additional enrichment** source.

---

## 3️⃣ Data storage & modeling (FAQ 6)

### Database choice


### Core schema (simplified)

**restaurants_raw_google**

* google_id
* name
* address
* lat, lon
* rating
* review_count
* category

**restaurants_raw_yelp**

* yelp_id
* name
* address
* lat, lon
* rating
* review_count
* price_range

**restaurants_integrated**

* unified_restaurant_id
* google_id
* yelp_id
* canonical_name
* canonical_address
* lat, lon
* google_rating
* yelp_rating
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
* Yelp ratings tend to be more conservative
* Peripheral areas have lower data completeness
