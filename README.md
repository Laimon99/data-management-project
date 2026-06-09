# Bicocca Data Management Project

## **Consistency and Quality of Online Restaurant Reviews in the Milan Area**

![Image](https://www.mapaplan.com/travel-map/milan-city-top-tourist-attractions-printable-street-plan-guide/high-resolution/milan-top-tourist-attractions-map-23-best-restaurants-dining-central-district-area-outline-layout-best-locations-visit-high-resolution.jpg)

![Image](https://images.squarespace-cdn.com/content/v1/5876d8d6e3df28c4d83ae377/1753791038525-ZICT8ERD8HT385S6MX4O/milan-milano-italy-brera-centro-storico-ip-03.jpg)

![Image](https://www.explore-italian-culture.com/images/osteria-di-brera-milan.jpg)

![Image](https://www.thetrainline.com/cms/media/5793/empty-seats-at-restaurant-in-milan-italy.jpg?height=440\&mode=crop\&quality=70\&width=660)

---
## TODO:
- [x] - [Find datasets and come up with research questions](#1️⃣-domain--research-questions)
- [x] - [Data Acquisition](#2️⃣-data-sources-faq-5--acquisition):
  - [x] - [Google Maps](services/extract/google_places_api/)
  - [x] - [TripAdvisor](services/extract/tripadvisor_scraper/)
  - [x] - [The Fork](services/extract/thefork_scraper/)
- [x] - [Store in Mongo](services/load/mongo/)
- [x] - [Enrich TripAdvisor with geo data](services/transform/tripadvisor_clean/)
- [x] - [Integrate 3 datasets](#5️⃣-data-integration--enrichment):
  - [x] - [schemas transformation](services/transform/) ([google_clean](services/transform/google_clean/), [tripadvisor_clean](services/transform/tripadvisor_clean/), [thefork_clean](services/transform/thefork_clean/))
  - [x] - [schemas matching](services/transform/entity_resolution/) ([schema-matching.md](docs/schema-matching.md), [schema-correspondences.md](docs/schema-correspondences.md))
  - [x] - [schemas integration](services/transform/unified_dataset/)
- [ ] - [Data profiling / data quality](services/quality_assessment/)
  - [x] - [pre integration](docs/data-quality-assessment.md) ([report](report/pre_integration/main.pdf))
  - [ ] - [post integration](report/post_integration/)
- [ ] - Load cleaned and integrated collections to [Clickhouse](docker-compose.yml)
- [ ] - Make atleast 2 queries on final dataset to answer some questions
- [ ] - Submit a project:
  - [ ] - Write a [final report](report/final/)
  - [ ] - Create a [presentation](report/final/)
  - [ ] - Create [operational guide](REPRODUCTION_OF_PROJECT.md) for reproduction of the project
  - [ ] - Upload to Google Drive and send to the professor 

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
If the current PowerShell session does not recognize `uv` immediately after install,
refresh the session `PATH` before continuing:
```powershell
$env:Path = "$HOME\.local\bin;$env:Path"
```

* Any **Chromium-based browser** — Brave, Chrome, Edge, Vivaldi, Opera, or Chromium
  (optional, for the Tripadvisor scraper; falls back to Playwright's bundled
  Chromium if none is found)

* **`pdflatex`** — optional, only needed to compile `report/pre_integration/main.pdf`.
  On macOS, install it with:
  ```bash
  brew install --cask mactex-no-gui
  ```
  On Windows, install a TeX distribution such as
  [MiKTeX](https://miktex.org/download) or [TeX Live](https://tug.org/texlive/windows.html),
  then open a new PowerShell session so `pdflatex` is on `PATH`.

  On macOS, after installation, open a new terminal. If `pdflatex` is still not
  found, add:
  ```bash
  export PATH="/Library/TeX/texbin:$PATH"
  ```

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

The scraper uses a two-loop workflow. If `tripadvisor_list_restaurant.txt` is absent,
the first loop starts from Tripadvisor's Milan listing page. Starting URL:
[Tripadvisor Milan restaurants](https://www.tripadvisor.it/Restaurants-g187849-Milan_Lombardy.html).
It scans each
`data-automation="restaurantCard"`, extracts child links beginning with
`/Restaurant_Review-`, deduplicates them, writes the URL list after every listing page,
and follows the `data-smoke-attr="pagination-next-arrow"` / `aria-label="Pagina
successiva"` href to paginate. If the URL file already exists, the scraper skips this
first loop and reuses it.

The second loop reads the resulting 7,539 Tripadvisor restaurant URLs for the Milan area
from `tripadvisor_list_restaurant.txt`, applies the checkpoint to skip already processed
URLs, and visits each restaurant page to extract the full venue profile.

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
`data/raw/thefork/thefork_milan_restaurants_enriched.json`. Milan listing pages were
scraped first to collect restaurant URLs/source ids and listing fallback fields, then
deduplicated and enriched from detail pages using JSON-LD, embedded JSON, visible HTML,
links/attributes, and fallbacks. The final run was produced on **2026-06-06** by
splitting detail enrichment across two machines with the GraphQL/CDP parallel proxy
workflow; the merged output was completed with a targeted run for 2 missing records,
yielding **1,344 unique restaurants**, all with `detail_scraped=true`.

| Detail run | Value |
|---|---|
| Date | **2026-06-06** |
| Workers | Windows slots 0-6; Mac Mini slots 7-13 |
| Saved reviews cap | 15 per restaurant |
| Final validation | 1,344 unique restaurants, all detail enriched |

Collection caveats are documented in
[`DATASET_CHANGES.md`](docs/the_fork_migration/DATASET_CHANGES.md):
`website`, `social_links`, `phone_number`, and `email` are empty in the final file,
and `discount` only reflects offers visible at collection time.

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

* **MongoDB** (`mongo:7`) — current document **system of record** for raw, clean,
  entity-resolution, and integrated collections. Starts on a plain `docker compose up`.
* **ClickHouse** (`clickhouse/clickhouse-server:26.3`, LTS) — the columnar engine for
  a future flat analytics export and analytical queries. It is scaffolded behind the
  opt-in `analytics` profile, so a plain `up` runs Mongo only.

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

Pre-integration baseline profiling is implemented as [`services/quality_assessment`](services/quality_assessment/README.md). It reads the three raw MongoDB collections and produces structured quality metrics, weighted scores, field-coverage tables, anomaly logs, a Markdown report, and LaTeX tables for the PDF report.

```bash
uv run quality-assessment
```

Outputs: `data/quality/`, [`docs/data-quality-assessment.md`](docs/data-quality-assessment.md), `report/pre_integration/tables/`.

To regenerate the full quality report PDF from the current raw datasets, run:

```bash
uv run quality-assessment && cd report/pre_integration && pdflatex -interaction=nonstopmode -halt-on-error main.tex && pdflatex -interaction=nonstopmode -halt-on-error main.tex
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\report\pre_integration\build_report.ps1
```

### Quality dimensions

| Dimension | What it measures |
|---|---|
| Completeness | % non-missing values across all profiled fields |
| Critical completeness | Coverage of fields required for matching and rating analysis |
| Validity / consistency | Present values matching source-specific formats (rating scale, phone/URL/email shape, price format, etc.) |
| Uniqueness | Duplicate source identifiers and duplicate normalized name/address pairs |
| Timeliness | Refreshability based on collection duration vs a 48h target |
| Reliability | Share of records with review count ≥ 20 (below that, ratings are sparse evidence) |
| Overall score | Weighted roll-up of the above |

### Pre-integration scores (current dataset)

| Source | Records | Quality score | Completeness | Critical | Validity | Spatial | Timeliness | Reliable reviews |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Google Places | 10 808 | 93.16% | 93.79% | 98.15% | 100.00% | 100.00% | 67.23% | 79.50% |
| Tripadvisor | 7 539 | 72.28% | 84.34% | 99.78% | 99.99% | 0.00% | 43.75% | 53.10% |
| TheFork | 1 344 | 97.63% | 76.15% | 98.88% | 100.00% | 100.00% | 95.83% | 88.84% |

Tripadvisor's 0% spatial readiness is expected — the raw scraper ships no coordinates; geocoding is added by the `tripadvisor_clean` transform.

---

## 5️⃣ Data integration & enrichment

The integration stage follows the following workflow: first create clean source schemas, then discover correspondences, then build the integrated schema and mapping rules.

### 01. Schema transformation / pre-integration

* **Input**: 3 source schemas from Google, Tripadvisor, and TheFork raw collections.
* **Output**: 3 source schemas **homogeneized** into comparable clean collections.
* **Methods used**: model transformations based on reverse engineering of the raw extractor
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

* **Input**: 3 homogeneized cleaned schemas.
* **Output**: auditable candidate correspondences between Google, Tripadvisor, and
  TheFork records in `entity_resolution_candidates`.
* **Methods used**: blocking, feature computation, calibrated scoring thresholds,
  chain-aware hardening, and later LLM/manual adjudication of uncertain pairs.

Restaurants do **not share IDs**, so integration depends on record linkage. The current
implemented record-linkage service is
[`transform.entity_resolution`](services/transform/entity_resolution/README.md).
Google is always the anchor: the service creates Google × Tripadvisor and Google ×
TheFork candidate pairs, but it does **not** directly match Tripadvisor × TheFork.

Baseline run:

```bash
uv run dataman-entity-resolve --dry-run
uv run dataman-entity-resolve --replace-destination
```

This writes candidate pair documents into MongoDB collection
`dataman.entity_resolution_candidates`. Each pair is keyed by
`<google_place_id>:<source_id>` and stores the Google id, source id, block strategy,
score, score components, effective thresholds, provisional label, chain flags, and a
nullable `llm_label`.

Thresholds are calibrated from candidate samples. Normal venues and chain-brand venues
are sampled separately because chain branches such as McDonald's, La Piadineria,
Spontini, and Burger King need stricter branch-level evidence.

```bash
# Export normal-venue candidates for hand labeling.
uv run dataman-er-calibrate export \
  --output data/quality/entity_resolution_calibration_normal.csv \
  --sample-size 400 \
  --source all \
  --chain-filter non_chain

# Manually label this CSV using the available row evidence; use web search for separate
# ambiguous cases. Fill human_label with MATCH or NON_MATCH.

uv run dataman-er-calibrate analyze \
  data/quality/entity_resolution_calibration_normal.csv

# Export chain-venue candidates for hand labeling.
uv run dataman-er-calibrate export \
  --output data/quality/entity_resolution_calibration_chains.csv \
  --sample-size 200 \
  --source all \
  --chain-filter chain

# Manually label this CSV using the available row evidence; use web search for separate
# ambiguous cases. Fill human_label with MATCH or NON_MATCH.

uv run dataman-er-calibrate analyze \
  data/quality/entity_resolution_calibration_chains.csv
```

The current calibrated thresholds are:

* Tripadvisor normal: `dmin=0.58`, `dmax=0.63`
* TheFork normal: `dmin=0.86`, `dmax=0.94`
* Tripadvisor chain: `dmin=0.49`, `dmax=0.52`
* TheFork chain: `dmin=0.76`, `dmax=0.79`

Final calibrated rewrite:

```bash
uv run dataman-entity-resolve --replace-destination \
  --dmin-tripadvisor 0.58 \
  --dmax-tripadvisor 0.63 \
  --dmin-thefork 0.86 \
  --dmax-thefork 0.94 \
  --dmin-chain-tripadvisor 0.49 \
  --dmax-chain-tripadvisor 0.52 \
  --dmin-chain-thefork 0.76 \
  --dmax-chain-thefork 0.79
```

The final candidate collection can be inspected with:

```bash
uv run python scripts/inspect_er_candidates.py
```

The current calibrated run produces 137,880 candidate pair documents:

* `MATCH`: 5,218
* `NON_MATCH`: 131,655
* `UNCERTAIN`: 906
* `UNBLOCKABLE`: 101

By source, this is 4,303 Tripadvisor matches and 915 TheFork matches against the Google
anchor pool. Remaining `UNCERTAIN` rows are the review queue for the future LLM/manual
adjudication step.

The output remains a candidate/evidence collection, not the final integrated restaurant
collection. The future LLM/manual step reads `entity_resolution_candidates` and updates
only `llm_label`; it does not generate new source records.

Integration quality is measured with false matches, missed matches, and ambiguous
matches. See [`docs/PIPELINE.md`](docs/PIPELINE.md) for the current workflow.

### 03. Schemas integration and mapping generation

* **Input**: homogeneized source schemas plus discovered correspondences.
* **Output**: an integrated schema plus mapping rules between the integrated schema and the input source schemas.
* **Methods used**: conflict classification and conflict-resolution transformations.

The integrated target is implemented by
[`transform.unified_dataset`](services/transform/unified_dataset/README.md):

```bash
uv run dataman-unify --dry-run
uv run dataman-unify --replace-destination
```

The service writes two MongoDB collections:

* `entity_resolution_links` — selected one-to-one Google × Tripadvisor and Google ×
  TheFork links, using `llm_label` when present and the automatic ER `label` otherwise.
* `restaurants_integrated` — final Google-seeded restaurant-rating collection, one
  document per dining and operational Google anchor.

The current materialized run writes **10,054 integrated restaurant documents**, with
**3,924 Tripadvisor links**, **908 TheFork links**, and **745 all-three-platform**
restaurants.

`restaurants_integrated` keeps source-specific evidence nested under `sources.google`,
`sources.tripadvisor`, and `sources.thefork`, while exposing the analytical fields
needed for rating comparison at the top level: canonical name/address/coordinates,
normalized per-platform ratings, review counts, `rating_avg_5`, `rating_range_5`,
platform-membership booleans, top-level website/phone evidence, and normalized
`price_level`. The Spark-style schema, and the conflict-handling strategy applied to each
top-level field (mapped to the Bleiholder & Naumann ignoring/avoiding/resolution
taxonomy), are documented in
[`integrated-dataset-schema.md`](services/transform/unified_dataset/integrated-dataset-schema.md).

Conflict resolution is chosen per field by the value's role: authoritative identity and
geography always take Google (*Trust your friends*); per-platform ratings and review
counts are deliberately kept side by side for comparison (*Consider all possibilities*);
`rating_avg_5`/`rating_range_5` are mediated aggregates (*Meet in the middle*); `website`
prefers a value over null and falls back to Google on disagreement; `phones` keeps the
de-duplicated union; and `price_level` is decided by majority vote across the three
normalized price signals (*Cry with the wolves*).

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
