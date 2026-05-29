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
printf "DATAMAN_GOOGLE_PLACES_API_KEY=your_key_here\n" > .env
```

The key must have **Places API (New)** enabled in Google Cloud
(*APIs & Services → Library → "Places API (New)" → Enable*) — the legacy
Places API will not work. `.env` is gitignored; the key is never written to
any log, file, or output document.

### Quick test — load ~10 venues from Milan centre

For a small smoke test around Piazza del Duomo, constrain the search area to the
whole-city fallback circle and cap the result count:

```bash
echo "DATAMAN_OUTER_RADIUS_M=500" >> .env
uv run google-places-api-extract list --whole-city --max-results 10
```

`--whole-city` restricts the run to the single whole-city circle (Duomo +
`DATAMAN_OUTER_RADIUS_M`). The circle is still tiled internally, so this may make
more than one API call; `--max-results` stops the run once enough unique venues
have been seen. Without `--whole-city`, the default run also tiles the dense
neighbourhood anchors (see below) and ignores `DATAMAN_OUTER_RADIUS_M` for those.

A JSON `ListReport` is printed to stdout (`tiles_processed`, `unique_places`,
`pages_fetched`, `errors`) and the venues land in `data/restaurants_seed.jsonl`.
Inspect them:

```bash
head data/restaurants_seed.jsonl | uv run python -c \
  "import sys, json; [print(json.loads(l)['name'], '—', json.loads(l)['formatted_address']) for l in sys.stdin]"
```

The run is idempotent: completed tiles are recorded in
`data/checkpoints/list_tiles.json` and skipped on re-run. Clear or replace that
checkpoint file to force a re-fetch.

### Enrich with full Place Details (Mode 2)

```bash
uv run google-places-api-extract detail --all                 # enrich every seed venue
uv run google-places-api-extract detail --place-id <PLACE_ID> # or a single venue
```

Mode 2 merges the full raw Place Details payload into each seed document,
preserving the seed fields. Already-enriched venues are tracked in
`data/checkpoints/detail_done.txt` and skipped on re-run.

> CLI forms are interchangeable: `google-places-api-extract list` ≡
> `google-places-api-extract --mode list`, and likewise for `detail`.

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
uv run google-places-api-extract list          # whole-city circle + all neighbourhood anchors
uv run google-places-api-extract detail --all
```

Flags narrow the coverage (use at most one):

```bash
uv run google-places-api-extract list --whole-city               # whole-city circle only
uv run google-places-api-extract list --all-neighbourhoods       # all anchors only, no city circle
uv run google-places-api-extract list --neighbourhood navigli_1  # a single named anchor
```

Override the anchors via `DATAMAN_NEIGHBOURHOODS` (JSON list of
`{name, lat, lon, outer_radius_m}`); set it to `[]` so the default run covers
only the whole-city circle.

### Tripadvisor scraper extract

The Tripadvisor Playwright scraper is packaged as
`src/tripadvisor_scraper_extract`. Runtime files are written under
`data/tripadvisor/`; the bundled restaurant URL list is copied there on first
run if no URL file exists yet. See `docs/tripadvisor-scraper-extract.md` for
runtime paths and browser setup details.

```bash
uv run tripadvisor-scraper-extract --order bottom
```

Use `--order bottom` when another teammate is scraping from the top of the URL
list. The default is `--order top`. The scraper auto-detects Brave on macOS,
Windows, and Linux; pass `--brave-path <path>` if Brave is installed somewhere
non-standard.

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

### Source A — Google Maps / Google Places API (implemented Stage 1)

* **Type**: Official API via Places API (New)
* **Data**:

  * Restaurant name
  * Address
  * Coordinates (lat/lon)
  * Rating
  * Number of reviews
  * Google place types and primary type
  * Optional full Place Details payload
* **Why**:

  * High coverage in Milan
  * Rich metadata
  * Coordinates become the project geographic backbone
* **Tools**:

  * Python + `httpx`
  * Tiled Nearby Search + Place Details
  * Raw JSONL seed output in `data/restaurants_seed.jsonl`

### Source B — Tripadvisor (scraper extract added)

* **Type**: Web scraping or another reproducible acquisition path
* **Data**:

  * Scraped restaurant name
  * Address
  * Rating
  * Review count
  * Optional review text / recency fields
* **Why**:

  * Different user base from Google
  * Useful for cross-platform rating consistency analysis

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

### Current Stage 1 persistence

Stage 1 currently writes raw seed documents to JSONL:

**`data/restaurants_seed.jsonl`**

* one JSON object per Google place
* deduplicated by `place_id`
* includes raw `details` after enrichment
* treated as acquisition output, not the final DBMS design

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
