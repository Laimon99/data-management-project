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

> **Verifying via a `uv run <console-script>` after editing service code?** Run
> `uv sync --reinstall-package data-management-project` first — console scripts run an
> installed copy, not your live source. Tests (`uv run pytest`) always read source, so they need no resync.

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
Parsing is deferred to the pre-integration schema transformation
([`tripadvisor_clean`](services/transform/tripadvisor_clean/README.md)).

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
* **Data**: restaurant name, URL/source id, address, coordinates, rating, review count,
  cuisine, price range, discounts, opening hours, and review snippets when exposed
* **Why**: restaurant-specific booking/review platform; useful comparison against
  review-heavy general platforms

#### How the current dataset was collected

The current shareable dataset is
`data/raw/thefork/thefork_milan_restaurants_enriched.json`. It was collected by scraping
Milan listing pages, deduplicating restaurant URLs/source ids, then enriching each venue
from its detail page. Detail extraction prioritizes JSON-LD, embedded JSON, visible HTML,
links/attributes, and finally listing fallback data. For interrupted or blocked detail
runs, the scraper supports resume, delay, proxy/CDP, and GraphQL-over-CDP recovery
workflows; completed shards can be merged with `uv run thefork-merge-outputs`.

<!-- TODO: replace/extend this with teammate-provided run history:
     listing pages/ranges, detail-enrichment mode(s), retries/proxies/CDP usage,
     merge inputs, and final validation command/report. -->

| Field | Coverage |
|---|---|
| Venues scraped | **1,344** |
| Unique `source_id` | 100% |
| Detail page enriched | 100% |
| Address | 100% |
| Coordinates | 100% |
| Rating | 94.1% |
| Review count | 98.1% |
| Review snippets / reviews | 96.7% |
| Structured opening hours | 63.6% |

#### Running the TheFork scraper

The scraper is packaged as `services/extract/thefork_scraper`. It collects Milan
listings, then optionally enriches each restaurant from its detail page, writing
the raw enriched JSON output under `data/raw/thefork/`. It tries the installed Chrome
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

**TheFork: `data/raw/thefork/`**

* `thefork_milan_restaurants_enriched.json`: final listing + detail output loaded to MongoDB
* `thefork_milan_restaurants_normalized_partial.json`: resumable partial snapshot
* `thefork_milan_restaurants_normalized_partial.merge_report.json`: merge/audit report
* optional runtime folders such as `brave_automation_profile/`, `calibration/`, and
  `runs/` may be created during anti-bot recovery or distributed scraping

### Storage infrastructure

The project's stateful databases now run as reproducible **Docker** infrastructure,
defined in [`docker-compose.yml`](docker-compose.yml) so they behave identically on
macOS, Windows, and Linux:

* **MongoDB** (`mongo:7`) — current document **system of record** for raw and clean
  per-source collections. Starts on a plain `docker compose up`.
* **ClickHouse** (`clickhouse/clickhouse-server:26.3`, LTS) — the columnar engine for
  the future integrated ratings table and analytical queries. It is scaffolded behind
  the opt-in `analytics` profile, so a plain `up` runs Mongo only.

Both services persist their data in **named volumes**, so it survives
`docker compose down` and is removed only by an explicit `docker compose down -v`.
Health checks and host-port overrides (for when `27017`/`8123` are already taken) are
configured, and [`.env.example`](.env.example) works out-of-the-box for local dev
(no auth, localhost-only). The DBMS evaluation and rationale live in
[`docs/storage-design.md`](docs/storage-design.md).

### Loading raw data into MongoDB

The **Load** layer of the ELT pipeline is implemented as
[`services/load/mongo`](services/load/mongo/README.md). It moves the raw extractor files
from `data/raw/` into MongoDB as a **pure raw passthrough** (no transformation), keyed on each
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
and `--reset` clears a collection before loading.

| Source | Raw file | Natural key | MongoDB raw collection |
|---|---|---|---|
| Google | `data/raw/google_places/restaurants_seed.jsonl` | `place_id` | `restaurants_raw_google` |
| Tripadvisor | `data/raw/tripadvisor/tripadvisor_scraper_results.json` | `source_url` | `restaurants_raw_tripadvisor` |
| TheFork | `data/raw/thefork/thefork_milan_restaurants_enriched.json` | `source_id` | `restaurants_raw_thefork` |

Raw MongoDB documents keep the source fields exactly as the extractor wrote them, plus
`_id`, `_loaded_at`, and `_source_file` load metadata. Exact raw keys, loader flags, and
edge-case behaviour are documented in
[`services/load/mongo/README.md`](services/load/mongo/README.md); the wider load/ETL
design lives in [`docs/etl-design.md`](docs/etl-design.md).

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

The integration stage follows the following workflow: first create clean source schemas, then discover correspondences, then build the integrated schema and mapping rules.

### 01. Schema transformation / pre-integration

* **Input**: `n` source schemas from Google, Tripadvisor, and TheFork raw collections.
* **Output**: `n` source schemas **homogeneized** into comparable clean collections.
* **Methods used**: model transformation + reverse engineering of the raw extractor
  outputs and EDA findings.

This is implemented as the clean transform layer. After loading, each source is cleaned
**Mongo → Mongo** while the `restaurants_raw_*` collections stay immutable.

```bash
uv run google-clean        # restaurants_raw_google      → restaurants_clean_google
uv run tripadvisor-clean   # restaurants_raw_tripadvisor → restaurants_clean_tripadvisor
uv run thefork-clean       # restaurants_raw_thefork     → restaurants_clean_thefork
```

* **Google** ([`google_clean`](services/transform/google_clean/README.md)) — projects lean
  fields out of the raw `details` blob, normalizes name/city, lifts structured address
  parts, copies the authoritative coordinates (**never** re-geocoded), and flags dining
  relevance so non-dining venues can be excluded.
* **Tripadvisor** ([`tripadvisor_clean`](services/transform/tripadvisor_clean/README.md)) —
  type-repairs the Italian display strings, structures price/cuisine/hours/reviews, lifts
  `ta_location_id`, and **geocodes** the cleaned address via Nominatim (Tripadvisor ships
  no coordinates). Resumable; `--skip-geocode` for a fast clean-only pass.
* **TheFork** ([`thefork_clean`](services/transform/thefork_clean/README.md)) — parses the
  1NF-violation fields (price/cuisine/discount/hours), normalizes name/city/address,
  lifts `tf_id`, and slims reviews; already typed and geocoded upstream, so no type-repair
  or geocoding.

Each transform returns a `CleanReport` for the quality-assessment stage and documents its
homogeneized output schema in the service README, `eda-report.md`, and where present
`clean-dataset-schema.md`.

### 02. Correspondences investigation

* **Input**: `n` homogeneized source schemas.
* **Output**: homogeneized source schemas plus candidate correspondences between Google, Tripadvisor, and TheFork records.
* **Methods used**: techniques to discover correspondences, starting with blocking and similarity scoring before any expensive matching step.

Restaurants do **not share IDs**, so integration depends on record linkage. The planned matching workflow is:

1. **Blocking** by city and geographic proximity, e.g. distance under 200 meters.
2. **Similarity metrics** over normalized names and addresses, e.g. Levenshtein / Jaro-Winkler.
3. **Composite matching score** combining distance, name similarity, address similarity, and platform-specific evidence.
4. **Decision labels**: match, no match, uncertain.

Integration quality is measured with false matches, missed matches, and ambiguous
matches. See [`docs/PIPELINE.md`](docs/PIPELINE.md) for the current design sketch.

### 03. Schemas integration and mapping generation

* **Input**: homogeneized source schemas plus discovered correspondences.
* **Output**: an integrated schema plus mapping rules between the integrated schema and the input source schemas.
* **Methods used**: conflict classification and conflict-resolution transformations.

The planned integrated target is `restaurants_integrated`: one resolved restaurant per
row/document with source ids, canonical name/address, coordinates, per-platform ratings,
review counts, rating differences, match provenance, and data-quality flags. Mapping
rules must resolve naming/address conflicts, source-id conflicts, missing fields, rating
scale conflicts (TheFork 0-10 vs Google/Tripadvisor 0-5), and coordinate authority
(Google coordinates as backbone; Tripadvisor geocoded only for proximity blocking).

Mandatory query examples for the integrated dataset:

* Restaurants with **rating difference > 1 star**
* Average rating per platform by area
* Correlation between review count and rating variance


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
