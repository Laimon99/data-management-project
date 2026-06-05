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

* **[`uv`](https://github.com/astral-sh/uv)** —  package manager, it also manages Python automatically, no separate install needed.

macOS / Linux:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
Windows (PowerShell):
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
* Any **Chromium-based browser** — Brave, Chrome, Edge, Vivaldi, Opera, or Chromium
  (optional, for the Tripadvisor scraper; falls back to Playwright's bundled
  Chromium if none is found)

### Install

```bash
uv sync --extra dev          # install runtime + dev dependencies
uv run pre-commit install    # (optional) install git hooks
uv run pytest                # run the test suite
```

> New to `uv`, `pre-commit`, or **Docker**? See the [Developer Guide](docs/dev-guide.md).

### Configure API keys

macOS / Linux:
```bash
printf "DATAMAN_GOOGLE_PLACES_API_KEY=your_key_here\n" > .env
```
Windows (PowerShell):
```powershell
"DATAMAN_GOOGLE_PLACES_API_KEY=your_key_here" | Out-File -Encoding ascii .env
```

The key must have **Places API (New)** enabled in Google Cloud
(*APIs & Services → Library → "Places API (New)" → Enable*) — the legacy
Places API will not work.

---


## 2️⃣ Data sources (FAQ 5 – acquisition)

### Source A — Google Maps / Google Places API

* **Type**: Official API via Places API (New)
* **Data**: see [`dataset-schema.md`](services/extract/google_places_api/dataset-schema.md)
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

Both runs are idempotent. See [`services/extract/google_places_api/README.md`](services/extract/google_places_api/README.md) for flags, env vars, neighbourhood anchors, and examples.

---

### Source B — Tripadvisor

* **Type**: Web scraping via Playwright
* **Data**: see [`dataset-schema.md`](services/extract/tripadvisor_scraper/dataset-schema.md)
* **Why**: different user base from Google; Tripadvisor is the dominant international restaurant-review platform, making it essential for cross-platform rating consistency analysis
* **Tools**: Python + Playwright (Chromium), restaurant-page scraper, raw JSON output in `data/raw/tripadvisor/`

#### How the current dataset was collected

The scraper iterates over a pre-built list of 7,539 Tripadvisor restaurant URLs for
the Milan area (`tripadvisor_list_restaurant.txt`) and visits each page to extract
the full venue profile.

<!-- TODO: ask Edoardo how the original tripadvisor_list_restaurant.txt was obtained
     (search/listing pages crawled? export? third-party source?) -->

| Field | Coverage |
|---|---|
| Venues scraped | **7,539** |
| Rating | 99.8% |
| Review count | 100% |
| Address | 99.1% |
| Phone number | 90.1% |
| Cuisine type | 77.7% |
| Price range | 67.7% |
| Opening hours | 67.6% |
| Email | 46.9% |

All values are stored as strings exactly as rendered on the page (Italian locale):
comma decimal separators, parenthesised review counts, euro-glyph price bands.
Parsing is deferred to the integration stage.

#### Running the Tripadvisor scraper

The scraper is packaged as `services/extract/tripadvisor_scraper`. Runtime files are
written under `data/raw/tripadvisor/`. The scraper is checkpoint-aware — interrupted
runs resume from where they left off.

```bash
uv run tripadvisor-scraper-extract --order bottom
```

Use `--order bottom` when another teammate is already scraping from the top of the
URL list (default is `--order top`). The scraper auto-detects an installed
Chromium-based browser on macOS, Windows, and Linux, trying Brave, Chrome, Edge,
Vivaldi, Opera, and Chromium in that order; if none is found it falls back to
Playwright's bundled Chromium. Pass `--browser-path <path>` if your browser is
installed somewhere non-standard. (The old `--brave-path` flag still works as a
deprecated alias.)

---

### Source C — TheFork

* **Type**: Web scraping via Playwright
* **Data**:

  * Scraped restaurant name
  * Address
  * Rating
  * Review count
  * Optional booking/price metadata
* **Why**:

  * Restaurant-specific platform
  * Useful comparison against review-heavy general platforms

#### Running the TheFork scraper

The scraper is packaged as `services/extract/thefork_scraper`. It collects Milan
listings, then optionally enriches each restaurant from its detail page, writing
the normalized dataset under `data/raw/thefork/`. It tries the installed Chrome
channel, then Edge, then Playwright's bundled Chromium. See
`services/extract/thefork_scraper/README.md` for the full CLI reference and
`docs/antibot-comparison.md` for detail-page anti-bot behaviour.

```bash
uv run thefork-scraper-extract
```

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

### Storage infrastructure

The project's stateful databases now run as reproducible **Docker** infrastructure,
defined in [`docker-compose.yml`](docker-compose.yml) so they behave identically on
macOS, Windows, and Linux:

* **MongoDB** (`mongo:7`) — the document **system of records** for the raw nested seed
  and, later, per-platform records. Starts on a plain `docker compose up`.
* **ClickHouse** (`clickhouse/clickhouse-server:26.3`, LTS) — the columnar engine for
  the future integrated ratings table and analytical queries. Scaffolded behind the
  opt-in `analytics` profile, so a plain `up` runs Mongo only.

Both services persist their data in **named volumes**, so it survives
`docker compose down` and is removed only by an explicit `docker compose down -v`.
Health checks and host-port overrides (for when `27017`/`8123` are already taken) are
configured, and [`.env.example`](.env.example) works out-of-the-box for local dev
(no auth, localhost-only).

### Loading raw data into MongoDB

The **Load** layer of the ELT pipeline is implemented as
`services/load/mongo`. It moves the raw extractor files from `data/raw/` into the MongoDB
collections below as a **pure raw passthrough** (no transformation), keyed on each
source's natural identifier (`place_id`, `source_url`, `source_id`) so loads are
**idempotent** — re-running never creates duplicates.

First make sure the raw extractor files are present locally under **`data/raw`**
(Windows: `data\raw`). Either run the three extractors yourself (see above), or reuse our
shared output by copying the **`raw`** folder from our **Google Drive** into **`data/raw`**.
Either way you should end up with
`data/raw/google_places/restaurants_seed.jsonl`,
`data/raw/tripadvisor/tripadvisor_scraper_results.json`, and
`data/raw/thefork/thefork_milan_restaurants_enriched.json`.

```bash
docker compose up -d mongo          # start MongoDB (localhost:27017)
uv run dataman-load all             # load Google, Tripadvisor, and TheFork
```

The `docker compose` and `uv run` commands above are identical on macOS, Windows
(PowerShell), and Linux.

Each source is also loadable on its own (`uv run dataman-load google|tripadvisor|thefork`),
and `--reset` clears a collection before loading. See
[`services/load/mongo/README.md`](services/load/mongo/README.md) for the source registry,
load metadata, flags, and edge-case behaviour. The wider pipeline design lives in
[`docs/etl-design.md`](docs/etl-design.md) and the candidate DBMS evaluation in
[`docs/storage-design.md`](docs/storage-design.md).

### Storage shape

The `restaurants_raw_*` collections are populated by the load step above as a **raw
passthrough**: each document holds the source's fields **exactly as the extractor wrote
them** (field names differ per source), plus three reserved load-metadata keys (`_id`,
`_loaded_at`, `_source_file`). The `_id` is the source's natural key — `place_id`
(Google), `source_url` (Tripadvisor), `source_id` (TheFork). There is no normalization at
this stage; that is the job of the upcoming Transform step. Values are stored exactly as
the scraper wrote them, so they still look raw — e.g. Tripadvisor ratings are text like
`"5,0"` (Italian comma) and missing fields show up as the text `"NaN"`, while TheFork uses
real numbers and empty (`null`) values.

The indicative fields below show what each source carries — see
[`services/load/mongo/README.md`](services/load/mongo/README.md) for the exact keys.

**restaurants_raw_google** — keyed on `place_id`

* place_id
* name
* formatted_address, city
* latitude, longitude
* rating, user_rating_count
* types / primary_type
* details (raw Places details document)

**restaurants_raw_tripadvisor** — keyed on `source_url`

* source_url
* restaurant_name
* address
* rating, total_review
* cuisine_type, price_range
* review (raw scraped payload)

**restaurants_raw_thefork** — keyed on `source_id`

* source_id
* restaurant_name
* address, city, latitude, longitude
* rating, review_count
* cuisine_type, price_range
* reviews (raw scraped payload)

`restaurants_integrated` is the upcoming integration target.

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
