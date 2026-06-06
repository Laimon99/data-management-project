# TripAdvisor Scraper Extract Module

**Data Management Project** — Università Milano Bicocca (A.A. 2025-2026)  
**Module:** `services/extract/tripadvisor_scraper/`  
**Last Updated:** June 2026

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Architecture & Design](#architecture--design)
   - [Scraper Logic (v11)](#scraper-logic-v11)
   - [Multi-Browser Chromium Detection](#multi-browser-chromium-detection)
   - [Checkpoint & Resume System](#checkpoint--resume-system)
4. [Data Schema](#data-schema)
5. [Post-Processing: Geocoding (see the branch: tripadvsior-geocoding-enrichment)](#post-processing-geocoding)
6. [Installation & Setup](#installation--setup)
7. [Usage Guide](#usage-guide)
8. [Output Files & Structure](#output-files--structure)
9. [Troubleshooting](#troubleshooting)
10. [Performance & Metrics](#performance--metrics)
11. [Contributing & Development](#contributing--development)
12. [References & Further Reading](#references--further-reading)

---

## Overview

### Purpose

The **TripAdvisor Scraper Extract** module is a production-grade web automation tool designed to extract restaurant metadata, ratings, contact information, and customer reviews from TripAdvisor's Milan (Italy) restaurant listings. The module serves as a critical data collection pipeline within the broader data management project, supplying cleaned, structured JSON datasets to downstream analytical and machine learning workflows.

### Key Capabilities

- **Massive-Scale Data Extraction:** Automated scraping of 7,500+ restaurant records from TripAdvisor Milan
- **Robust Anti-Bot Evasion:** Playwright-based browser automation with realistic human-like delay patterns and fingerprint diversity
- **Fault-Tolerant Resume:** Checkpoint-based recovery from IP bans, network failures, and script interruptions
- **Structured Data Output:** Clean JSON format with 13 core restaurant attributes plus nested review data
- **Post-Processing Enrichment:** Optional geocoding layer to enrich address fields with GPS coordinates
- **Multi-Browser Support:** Automatic detection and launch of any Chromium-based browser (Brave, Chrome, Edge, Vivaldi, Opera)

### Target Complexity & Challenge

TripAdvisor represents a **hostile scraping environment** due to:

| Defense Layer | Mechanism |
|---|---|
| **TLS Fingerprinting** | Identifies non-browser HTTP clients immediately |
| **Browser Fingerprinting** | Canvas hash, WebGL renderer, font metrics analysis |
| **Behavioral Analytics** | Mouse velocity, scroll patterns, click timing detection |
| **IP Velocity Scoring** | Per-IP request rate limiting and banning |
| **Honeypot Links** | Invisible elements that trigger instant bans if clicked |
| **Dynamic CSS Classes** | Randomly generated class names rotated on each deployment |

This module overcomes these defenses through:
- Persistent browser profiles with real cookies and history
- Randomized inter-request delays (5–10 seconds between pages)
- Semantic DOM selectors anchored to stable `data-automation` and `data-test-target` attributes
- Native browser event simulation via Chrome DevTools Protocol (CDP)

---

## Quick Start

The Tripadvisor extractor is packaged in `services/extract/tripadvisor_scraper` and is runnable through `uv`.

### Run

```bash
uv run tripadvisor-scraper-extract --order bottom
```

Use `--order bottom` when another teammate is scraping from the top of the URL
list. The default is `--order top`.

## Browser compatibility

The scraper auto-detects Brave on macOS, Windows, and Linux. If Brave is
installed in a non-standard location, pass it explicitly:

```bash
uv run tripadvisor-scraper-extract --order bottom --brave-path "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
```

If Brave is unavailable, the scraper falls back to Playwright-managed Chromium.
That browser may need to be installed once:

```bash
uv run playwright install chromium
```

## Runtime files

Runtime data is kept out of `src` and written under `data/raw/tripadvisor/` by
default:

| File | Purpose |
|---|---|
| `tripadvisor_list_restaurant.txt` | Source URL list. A bundled copy is copied here on first run if absent. |
| `tripadvisor_scraper_results.json` | Accumulated extracted restaurant records. |
| `tripadvisor_checkpoint.json` | Resume state with processed and failed URLs. |
| `brave_automation_profile/` | Persistent browser profile for the scraper session. |

Override the runtime directory or URL file when needed:

```bash
uv run tripadvisor-scraper-extract --data-dir data/raw/tripadvisor_run_2
uv run tripadvisor-scraper-extract --url-file path/to/custom_urls.txt
```


### Output Files

After execution, three files are created in the current directory:

```
tripadvisor_list_restaurant.txt       # URL list (one per line)
tripadvisor_scraper_results.json      # Structured data output
tripadvisor_checkpoint.json           # Resume state
```

---

## Architecture & Design

### Scraper Logic (v11)

#### Two-Loop Pipeline Architecture

The scraper operates in a coordinated two-loop design:

```
┌─────────────────────────────────────────────────────────────┐
│ LOOP 1: URL EXTRACTION (Pagination Phase)                   │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  1. Navigate to BASE_URL (Milan restaurants listing)         │
│  2. User specifies number of pages to scrape                 │
│  3. FOR EACH PAGE:                                           │
│     a. Simulate human scroll with 300px scatters             │
│     b. Extract all <div data-automation="restaurantCard">    │
│     c. Isolate <a href="/Restaurant_Review-...">            │
│     d. Append URLs to tripadvisor_list_restaurant.txt        │
│     e. Wait 5–10 seconds (anti-bot delay)                    │
│     f. Click pagination button & navigate next page          │
│  4. Repeat until max pages reached or "next" button disabled │
│                                                               │
└─────────────────────────────────────────────────────────────┘
                            ↓
                    [URL LIST READY]
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ LOOP 2: FEATURE EXTRACTION (Scraping Phase)                 │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  1. Load checkpoint to find remaining URLs                   │
│  2. Load prior results (if any) from JSON                    │
│  3. FOR EACH RESTAURANT URL:                                 │
│     a. Wait 5–10 seconds (inter-restaurant delay)            │
│     b. Navigate to restaurant page                           │
│     c. Extract 11 core features (name, rating, address...)   │
│     d. Extract review array (author, title, text, date)      │
│     e. Append to JSON results                                │
│     f. Mark URL as processed in checkpoint                   │
│     g. 400–1200ms pauses between feature extractions         │
│  4. Save results incrementally after each restaurant         │
│  5. Resume on script restart from last checkpoint            │
│                                                               │
└─────────────────────────────────────────────────────────────┘
                            ↓
                  [STRUCTURED JSON READY]
                            ↓
            [OPTIONAL: GEOCODING ENRICHMENT]
```

#### Why This Design?

1. **Separation of Concerns:** URL extraction is I/O-light and fast; feature extraction is CPU-intensive and slow. Separating them allows independent resumption and progress tracking.

2. **Incremental Output:** Results are saved to JSON after each restaurant, not at the end. This protects against data loss and allows monitoring progress in real-time.

3. **Checkpoint-Based Resume:** The state file tracks which URLs have been processed, allowing seamless resumption after network failures or IP bans.

#### Selector Strategy: Defeating Dynamic CSS

TripAdvisor regenerates CSS class names on each deployment cycle (hours to days). The scraper **never relies on CSS classes**. Instead, all selectors anchor to semantic HTML attributes:

```python
# ✗ FRAGILE (breaks on CSS refactor)
page.locator('span.restaurant-rating')

# ✓ STABLE (semantic, survives refactors)
page.locator('div[data-automation="restaurantCard"]')
page.locator('div[data-test-target="reviews-tab"]')
page.locator('a[data-smoke-attr="pagination-next-arrow"]')
page.locator('a[href^="/Profile/"]')
```

These `data-automation`, `data-test-target`, and `data-smoke-attr` attributes are internal testing hooks — TripAdvisor's engineers use them for QA automation and have strong incentives to keep them stable. They survive CSS refactors because they encode *function*, not *style*.

#### Asyncio & Non-Blocking Delays

All timing delays use **async/await** with `page.wait_for_timeout()`, never `time.sleep()`:

```python
# ✗ BLOCKS ENTIRE THREAD
time.sleep(7.3)

# ✓ NON-BLOCKING (event loop continues processing)
await page.wait_for_timeout(7300)
```

This allows Playwright's internal C++ networking layer to continue processing HTTP responses and DOM mutations during idle periods, making the scraper more resource-efficient and behaviorally natural.

#### Randomized Delay Policy (Anti-Pattern Detection)

Delays are randomized across three temporal scales:

| Scale | Range | Purpose |
|---|---|---|
| **Inter-Page** | 5–10 seconds | Before paginating to next listing page |
| **Inter-Restaurant** | 5–10 seconds | Before navigating to each restaurant detail |
| **Inter-Feature** | 400–1200 ms | Between extracting consecutive fields on a single page |

Each delay uses `random.uniform()` to destroy statistical regularity. Anti-bot systems flag requests that arrive at exact intervals; true humans have variable attention spans.

#### Review & Author Extraction (v11 Schema)

Reviews are extracted from `div[data-test-target="reviews-tab"]` and stored as a JSON array:

```json
{
  "author": {
    "nickname": "ermanna46",           // Extracted from href="/Profile/ermanna46"
    "number_of_contribution": "54"     // From <span class="b">54</span> contributi
  },
  "title": "Ottima pizza!",
  "text": "Pizzeria molto carina con...",
  "date_of_publication": "27 maggio 2026"  // Cleaned from "Scritta in data 27 maggio 2026"
}
```

**Key v11 Update:** The `residence` field was removed from `author` because the majority of TripAdvisor users do not complete their profile location field, resulting in >40% `NaN` coverage. The schema is now lightweight and data-dense.

#### Brave Profile Persistence

The scraper uses `launch_persistent_context()` pointing to a real browser profile directory:

```python
context = await p.chromium.launch_persistent_context(
    user_data_dir="./browser_automation_profile",
    executable_path=resolved_browser_path,
    headless=False,
    args=['--disable-blink-features=AutomationControlled']
)
```

This profile carries:
- Real TripAdvisor session cookies
- Browser history (raises trust score)
- localStorage and IndexedDB state
- Full user font stack
- Randomized canvas/WebGL fingerprint (Brave Shields)

A sterile, ephemeral Chromium instance would be flagged immediately by TripAdvisor's fingerprinting database. A persistent profile is indistinguishable from a real user's browser.

---

### Multi-Browser Chromium Detection

#### Evolution from Brave-Only to Universal Chromium Support

**Original (v9-10):** Script hardcoded path to Brave Browser (`C:\Program Files\BraveSoftware\...`)  
**Current (v11+):** Automatic detection of any Chromium-based browser

#### Detection Priority Order

When launched without `--browser-path` override, the script searches for browsers in this order:

1. **Brave Browser** (Premium privacy features + fingerprint randomization)
2. **Google Chrome** (Ubiquitous, stable)
3. **Microsoft Edge** (Enterprise Windows standard)
4. **Vivaldi** (Advanced developer tools)
5. **Opera** (Lightweight, Chromium-based)
6. **Chromium** (Pure open-source)
7. **Playwright Bundled Chromium** (Fallback if none found)

#### Platform-Specific Paths

The detection scans platform-specific installation locations:

**Windows:**
```
C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe
C:\Program Files\Google\Chrome\Application\chrome.exe
C:\Program Files\Microsoft\Edge\Application\msedge.exe
... (+ 32-bit PROGRAMFILES(x86) variants)
```

**macOS:**
```
/Applications/Brave Browser.app/Contents/MacOS/Brave Browser
/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge
```

**Linux:**
```
/usr/bin/brave-browser
/usr/bin/google-chrome
/usr/bin/microsoft-edge
/snap/bin/chromium  (snap installations)
```

If hardcoded paths fail, the script falls back to `shutil.which()` to search the system `PATH`.

#### CLI Arguments

```bash
# Automatic detection (scans in priority order)
python -m extract.tripadvisor_scraper

# Force a specific browser
python -m extract.tripadvisor_scraper --browser-path /usr/bin/google-chrome

# Legacy argument (deprecated but functional)
python -m extract.tripadvisor_scraper --brave-path /path/to/brave
```

#### Portability Benefits

This multi-browser architecture allows:

- **Team Collaboration:** Different team members can use their preferred browser (no Brave installation required)
- **CI/CD Flexibility:** Automation pipelines can use lightweight Chromium in Docker containers
- **Cross-Platform:** Same script runs identically on Windows, macOS, and Linux
- **Graceful Degradation:** If no browser is installed, Playwright's bundled Chromium activates automatically (with reduced anti-bot efficacy)

---

### Checkpoint & Resume System

#### The Problem Solved

Large-scale scraping is inherently fragile:
- **IP Bans:** TripAdvisor may temporarily block the scraper after 1000+ requests
- **Network Failures:** Internet disconnections, timeout errors
- **Human Interruption:** User kills script, power outage, system crash

Without a checkpoint system, **all progress is lost**. The scraper must restart from zero.

#### The Solution: Atomic Checkpointing

Three files form the checkpoint triplet:

```json
[tripadvisor_list_restaurant.txt]
https://www.tripadvisor.it/Restaurant_Review-g187849-d1234567-...
https://www.tripadvisor.it/Restaurant_Review-g187849-d1234568-...
... (7,539 URLs total)

[tripadvisor_checkpoint.json]
{
  "processed_urls": [
    "https://www.tripadvisor.it/Restaurant_Review-g187849-d1234567-...",
    ... (2,150 completed)
  ],
  "failed_urls": [
    "https://www.tripadvisor.it/Restaurant_Review-g187849-d9999999-...",
    ... (47 failed)
  ],
  "last_update": "2026-05-27T14:33:22.101234"
}

[tripadvisor_scraper_results.json]
[
  { "restaurant_name": "Osteria Mario", ... },
  { "restaurant_name": "Pizzeria Luigi", ... },
  ... (2,150 records)
]
```

#### Resume Logic

On every script restart:

```python
checkpoint = load_checkpoint()
processed = set(checkpoint["processed_urls"])
all_urls = read_list("tripadvisor_list_restaurant.txt")
urls_to_scrape = [url for url in all_urls if url not in processed]

# Only scrape the pending URLs
for url in urls_to_scrape:
    data = extract_restaurant_features(url)
    results.append(data)
    mark_url_processed(checkpoint, url)
```

If the script is interrupted at restaurant #2150, restarting resumes from #2151. Maximum data loss is exactly one record.

#### Atomic Write-on-Success

After each successful extraction:

```python
# 1. Append to JSON
with open(JSON_FILE, "w") as f:
    json.dump(results, f)

# 2. Update checkpoint
mark_url_processed(checkpoint, url)
```

This order is critical: if extraction succeeds but the checkpoint write fails, the next restart will re-scrape the same restaurant (duplicate, but data-safe). If checkpoint write succeeds but extraction fails halfway, the next restart skips it (minimal data loss).

---

## Data Schema

### Input: `tripadvisor_list_restaurant.txt`

Plain text file, one URL per line:

```
https://www.tripadvisor.it/Restaurant_Review-g187849-d1234567-Milan_Lombardy.html
https://www.tripadvisor.it/Restaurant_Review-g187849-d1234568-Milan_Lombardy.html
https://www.tripadvisor.it/Restaurant_Review-g187849-d1234569-Milan_Lombardy.html
...
```

### Output: `tripadvisor_scraper_results.json`

JSON array of restaurant objects. Total: 7,539 records (Milan area).

#### Core Restaurant Fields

| Field | Type | Coverage | Example / Notes |
|---|---|---|---|
| `restaurant_name` | string | 100% | `"Osteria del Balabiott"` |
| `rating` | string | 99.8% | `"4,3"` (Italian locale, comma decimal). `"NaN"` for ~15 unrated venues. Use `.replace(",", ".")` for numeric parsing. |
| `total_review` | string | 100% | `"(278 recensioni)"` — includes surrounding Italian text. Extract integer with regex `r"\((\d+)"`. |
| `cuisine_type` | string | 77.7% | `"Italiana, Pizza"` (comma-separated). 260 unique values. `"NaN"` for 22.3% where TripAdvisor omits field. |
| `price_range` | string | 67.7% | One of: `"€"`, `"€€-€€€"`, `"€€€€"`, or `"NaN"`. Four distinct values only. |
| `number_photo_uploaded` | string | 78.9% | `"380"` (numeric string). `"NaN"` for 21.1%. |
| `address` | string | 99.1% | `"Piazza Vesuvio 13, 20144 Milano Italia"`. `"NaN"` for 0.9%. 99.1% contain "Milano". |
| `website` | string | 79.9% | Full URL or `"NaN"`. 20.1% of venues do not publish websites on TripAdvisor. |
| `phone_number` | string | 90.1% | `"+39 02 2316 3376"` (Italian format). `"NaN"` for 9.9%. |
| `email` | string | 46.9% | Email address or `"NaN"`. Only 46.9% of restaurants provide email contact via TripAdvisor. |
| `working_days_hours` | string | 67.6% | `"Domenica: 12.00-15.00 and 19.00-23.00; Lunedì: 12.00-15.00 and..."` — flattened with `and` separators. `"NaN"` for 32.4%. |
| `review` | array\|string | 88.6% | Array of review objects (see below) or literal string `"NaN"` for 11.4% (zero reviews or extraction failure). |

#### Review Object Schema

Stored within the `review` array:

```json
{
  "author": {
    "nickname": "ermanna46",            // From href="/Profile/ermanna46"
    "number_of_contribution": "54"      // From <span class="b">54</span> contributi
  },
  "title": "Ottima pizza!",
  "text": "Pizzeria molto carina con personale amichevole...",
  "date_of_publication": "27 maggio 2026"  // Cleaned from "Scritta in data 27 maggio 2026"
}
```

#### Data Integrity Notes

- **Encoding:** All text is UTF-8. Italian diacritics (à, è, ì, ò, ù) and special characters are preserved.
- **Locale:** Values are stored **exactly as rendered** on the Italian TripAdvisor website (comma decimals, Italian month names, etc.). Downstream pipelines must handle locale-aware parsing.
- **Whitespace:** Leading/trailing whitespace is stripped via `.strip()` during extraction, but embedded whitespace in review text is preserved.
- **Missing Data:** Encoded as the literal string `"NaN"` (not JSON `null`), for consistency and Excel/CSV import compatibility.

#### Example Complete Record

```json
{
  "restaurant_name": "Osteria del Balabiott",
  "rating": "4,5",
  "total_review": "(143 recensioni)",
  "cuisine_type": "Italiana, Piemontese",
  "price_range": "€€-€€€",
  "number_photo_uploaded": "47",
  "address": "Via Torino 19, 20123 Milano Italia",
  "latitude": "45.4637",
  "longitude": "9.1923",
  "website": "https://www.balabiott.it",
  "phone_number": "+39 02 8645 4994",
  "email": "NaN",
  "working_days_hours": "Lunedì-Giovedì: 12.00-15.00 and 19.00-23.00; Venerdì-Sabato: 12.00-15.00 and 19.00-23.30; Domenica: 12.00-15.00 and 19.00-23.00",
  "review": [
    {
      "author": {
        "nickname": "ermanna46",
        "number_of_contribution": "54"
      },
      "title": "Ottima cucina piemontese",
      "text": "Locale accogliente con una cucina di qualità. Personale attento e disponibile.",
      "date_of_publication": "3 marzo 2026"
    },
    {
      "author": {
        "nickname": "milaneza_foodie",
        "number_of_contribution": "127"
      },
      "title": "Consigliato!",
      "text": "Piatti deliziosi, ambiente piacevole. Un po' caro ma vale la pena.",
      "date_of_publication": "15 febbraio 2026"
    }
  ]
}
```

---

## Post-Processing: Geocoding (transform stage)

This scraper outputs address strings but **no coordinates**, and geocoding is **not**
part of the scraper. Coordinates are added downstream by the **transform stage**
(`services/transform/tripadvisor_clean`), which cleans the raw records and enriches the
cleaned address with latitude/longitude via Nominatim/OpenStreetMap.

➡️ See **[`services/transform/tripadvisor_clean/README.md`](../../transform/tripadvisor_clean/README.md)**
for how to run it, its CLI flags, rate-limiting/compliance, and output format.

### Motivation

TripAdvisor provides address strings but not geographic coordinates (latitude/longitude). For mapping, spatial analysis, and geospatial joins with other datasets, we must enrich the address field with GPS coordinates.

### Tool: geopy + Nominatim

The `geocoding_restaurant.py` module uses:

- **geopy:** Python library for geolocation services
- **Nominatim:** Free, open-source geocoder (OpenStreetMap-based)

```python
from geopy.geocoders import Nominatim

geolocator = Nominatim(user_agent="data-management-project-tripadvisor-v11")
location = geolocator.geocode("Via Torino 19, 20123 Milano Italia")
print(location.latitude, location.longitude)
# Output: 45.4637, 9.1923
```

### Rate-Limiting & Compliance

Nominatim's Terms of Service **require:**

1. **User-Agent Header:** Must identify your application uniquely (not a generic "Mozilla/5.0")
2. **Delay Between Requests:** Minimum **1.5 seconds** between consecutive requests

The script enforces these:

```python
geolocator = Nominatim(
    user_agent="data-management-project-tripadvisor-v11",  # Unique identifier
    timeout=10
)

# Delay between requests
time.sleep(1.5)  # Blocking sleep is acceptable here (I/O-bound, not large-scale)
location = geolocator.geocode(address)
```

### Failure Handling

| Input | Output |
|---|---|
| Valid address (e.g., `"Via Torino 19, 20123 Milano"`) | Coordinates (e.g., `45.4637`, `9.1923`) |
| Address not found in Nominatim | `"NaN"` for both lat/long |
| Network error / timeout | `"NaN"` for both lat/long, continue to next |
| Input address already `"NaN"` | Skip geocoding, output `"NaN"` for both |

### Output File Structure

Geocoded data is written to `tripadvisor_scraper_results_geocoded.json`:

```json
{
  "restaurant_name": "Osteria del Balabiott",
  "rating": "4,5",
  ...
  "address": "Via Torino 19, 20123 Milano Italia",
  "latitude": "45.4637",           // ← NEW
  "longitude": "9.1923",           // ← NEW
  "website": "https://www.balabiott.it",
  ...
}
```

### Running the transform (clean + geocode)

Geocoding is no longer part of this scraper — it is a sub-step of the **transform** stage
(`services/transform/tripadvisor_clean`). After scraping and loading into MongoDB
(`uv run dataman-load tripadvisor`), the transform cleans the raw records and geocodes the
cleaned address **Mongo → Mongo** into `restaurants_clean_tripadvisor`:

```bash
uv run tripadvisor-clean            # clean + geocode the full dataset
uv run tripadvisor-clean --limit 20 # quick test slice
uv run tripadvisor-clean --skip-geocode  # fast clean-only pass
```

See `services/transform/tripadvisor_clean/README.md` for `--limit`, `--skip-geocode`,
`--reset`, `--delay`, and `--timeout`.

### Performance Metrics

Typical throughput: **2,400 records / 40 minutes** (1.5s delay × 2,400 = 3,600 seconds / 60 min = 60 min overhead)

For 7,539 records: **~3 hours of geocoding time**

```
────────────────────────────────────────────────────────
[DONE] File saved to 'tripadvisor_scraper_results_geocoded.json'
       ✔  Coordinates found   : 7,100
       ✘  Not found          : 396
       ⊘  Skipped (addr NaN) : 43
       Total                 : 7,539
────────────────────────────────────────────────────────
```

---

## Installation & Setup

### System Requirements

| Component | Requirement | Notes |
|---|---|---|
| **Python** | 3.8+ | 3.10+ recommended for better asyncio performance |
| **Browser** | Brave / Chrome / Edge / Vivaldi / Opera | Any Chromium-based; auto-detected. Playwright's bundled Chromium used as fallback. |
| **OS** | Windows / macOS / Linux | Tested on Windows 10/11, macOS 12+, Ubuntu 20.04+ |
| **RAM** | 4 GB minimum | 8 GB recommended for concurrent process overhead |
| **Disk** | 500 MB free | JSON output (~80 MB for 7,539 records) + Playwright cache |

### Dependencies

**Core dependencies:**

- **playwright** (2.0+) — Browser automation
- **geopy** (2.3+) — Geocoding (optional, for enrichment)
- **aiofiles** (23.0+) — Async file I/O (optional)

---

## Usage Guide

### Running the Full Pipeline

#### Option 1: Automatic (Recommended)

```bash
python -m extract.tripadvisor_scraper
```

The script will:

1. Auto-detect an installed Chromium browser (Brave → Chrome → Edge → ...)
2. Prompt you to accept cookies in the browser window
3. Ask how many pages of restaurants to scrape (press `[ENTER]` for all)
4. Extract restaurant URLs (Loop 1)
5. Scrape features and reviews for each restaurant (Loop 2)
6. Save results incrementally to JSON

#### Option 2: Force a Specific Browser

```bash
python -m extract.tripadvisor_scraper --browser-path /usr/bin/google-chrome
```

#### Option 3: Resume From Interruption

If the script was interrupted:

```bash
python -m extract.tripadvisor_scraper

# The checkpoint system automatically loads the prior state
# and skips all previously processed restaurants
```

#### Option 4: Clean + Geocode (transform stage)

```bash
# After scraping and loading into MongoDB (uv run dataman-load tripadvisor):
uv run tripadvisor-clean

# This reads restaurants_raw_tripadvisor and writes cleaned+geocoded docs
# (Mongo -> Mongo) into restaurants_clean_tripadvisor.
```

### Runtime Interaction

The script is designed to be attended to during execution:

```
[*] TRIPADVISOR SCRAPER V11 - Avviamento
[!] Pagina inizializzata sul browser.
[!] Accetta manualmente i cookie o chiudi i pop-up grafici nella finestra di Brave.
>>> Premi [INVIO] quando la pagina è pulita per iniziare...
```

**What to do:**
1. The Brave/Chrome window opens with the Milan restaurants page
2. Accept any cookie consent banners by clicking in the browser window
3. Close any modal dialogs (ads, promotions)
4. Return to the terminal and press `[ENTER]`

```
>>> Quante pagine vuoi scansionare? (Premi [INVIO] per scansionare TUTTE):
```

**What to do:**
- Enter a number (e.g., `5` to scan 5 pages = ~200 restaurants)
- Press `[ENTER]` with no input to scan all pages (7,539 restaurants)

### Estimated Runtimes

| Scope | Approximate Duration | Notes |
|---|---|---|
| 1 page (30 restaurants) | 1–2 hours | Includes 5–10s delays between pages and restaurants |
| 10 pages (300 restaurants) | 10–15 hours | Non-linear due to variable review extraction time |
| All pages (7,539 restaurants) | 80–120 hours | Continuous operation over 3–5 days |
| Geocoding (post-process) | 3 hours | 1.5s delay × 7,539 records |

**Optimization tips:**
- Run overnight or on a dedicated machine
- Use a high-speed internet connection (reduces timeouts)
- Consider running on a cloud VM to avoid IP bans (residential ISPs have stricter limits)

---

## Output Files & Structure

### `tripadvisor_list_restaurant.txt`

**Purpose:** Source-of-truth URL list from pagination loop.

**Format:** Plain text, one URL per line.

**Example:**
```
https://www.tripadvisor.it/Restaurant_Review-g187849-d10648847-Milan_Lombardy.html
https://www.tripadvisor.it/Restaurant_Review-g187849-d10648848-Milan_Lombardy.html
...
```

**Properties:**
- One per line (no CSV header)
- URLs are unique (duplicates removed during extraction)
- All follow `/Restaurant_Review-g187849-dXXXXXXX-` pattern (g187849 = Milan GeoID)

### `tripadvisor_scraper_results.json`

**Purpose:** Main output; structured restaurant metadata and reviews.

**Format:** JSON array of objects (see [Data Schema](#data-schema) section).

**Example (single record):**
```json
{
  "restaurant_name": "Pizzeria da Mario",
  "rating": "4,5",
  "total_review": "(89 recensioni)",
  ...
  "review": [
    { "author": { ... }, "title": "...", ... },
    ...
  ]
}
```

**Properties:**
- UTF-8 encoded (preserves Italian diacritics)
- Formatted with 2-space indentation (human-readable)
- One record per restaurant; 7,539 records total for full run
- File size: ~80 MB for complete dataset

### `tripadvisor_checkpoint.json`

**Purpose:** Resume state for fault tolerance.

**Format:** JSON object with three keys.

**Example:**
```json
{
  "processed_urls": [
    "https://www.tripadvisor.it/Restaurant_Review-g187849-d10648847-Milan_Lombardy.html",
    ...
  ],
  "failed_urls": [
    "https://www.tripadvisor.it/Restaurant_Review-g187849-d99999999-Milan_Lombardy.html",
    ...
  ],
  "last_update": "2026-05-27T14:33:22.101234"
}
```

**Properties:**
- Updated after each successful restaurant extraction
- Consumed at script startup to determine remaining work
- Allows resume-from-checkpoint without data loss

### `tripadvisor_scraper_results_geocoded.json`

**Purpose:** Enriched output with GPS coordinates (optional, post-processing).

**Format:** Identical to `tripadvisor_scraper_results.json` with added `latitude` and `longitude` fields.

**Example (excerpt):**
```json
{
  "restaurant_name": "Pizzeria da Mario",
  "rating": "4,5",
  ...
  "address": "Via Torino 19, 20123 Milano Italia",
  "latitude": "45.4637",
  "longitude": "9.1923",
  ...
}
```

**Properties:**
- Generated by `geocoding_restaurant.py`
- Contains all fields from original JSON plus lat/long
- Coordinates are strings (not numbers) for consistency with other fields

---

## Troubleshooting

### Common Issues & Solutions

#### Issue: `FileNotFoundError: Brave Browser not found`

**Cause:** Brave is not installed, and auto-detection failed to find another browser.

**Solution:**
```bash
# Option 1: Install Brave
# https://brave.com/download

# Option 2: Use installed Chrome
python -m extract.tripadvisor_scraper --browser-path "C:\Program Files\Google\Chrome\Application\chrome.exe"

# Option 3: Let Playwright's bundled Chromium be used (less effective anti-bot)
# Do not pass --browser-path; script will auto-fallback
```

#### Issue: `TimeoutError: page.goto(url) timeout exceeded`

**Cause:** TripAdvisor is slow to respond or blocking the request.

**Solution:**
```python
# Increase timeout in scraper.py (default 30s)
await page.goto(url, wait_until="domcontentloaded", timeout=60000)  # 60 seconds
```

#### Issue: Script stops with `Accesso è temporaneamente limitato` (Temporarily blocked)

**Cause:** TripAdvisor has rate-limited or temporarily blocked the IP.

**Symptom:** BEEP sound from the terminal; browser shows Italian error message.

**Solution:**
1. **Manual CAPTCHA:** Solve any CAPTCHA in the browser window (if prompted)
2. **Wait 15–30 minutes:** Then press `[ENTER]` in the terminal to resume
3. **Change IP:** If blocks persist:
   - Use a VPN (reduces detection risk but violates some ISPs' ToS)
   - Restart router to get a new ISP-assigned IP
   - Run on a cloud VM in a different region

#### Issue: JSON file is empty after 2+ hours of scraping

**Cause:** Loop 1 extracted URLs but Loop 2 didn't find the JSON results file.

**Check:**
```bash
# Verify files exist
ls -la tripadvisor_*.* 

# Check file sizes
du -h tripadvisor_*.*

# If tripadvisor_scraper_results.json is 0 bytes:
# Loop 2 encountered an extraction error on every restaurant
```

**Debug:**
```python
# Add verbose logging in scraper.py
if restaurant_data:
    print(f"   [✓] Extracted: {restaurant_data['restaurant_name']}")
else:
    print(f"   [!] EXTRACTION FAILED for {url}")
    print(f"       Page title: {await page.title()}")
```

#### Issue: Reviews are missing (`"review": "NaN"` for all records)

**Cause:** Review extraction selector failed; possibly TripAdvisor updated their HTML structure.

**Debug:**
```python
# Check if reviews-tab is present
await page.goto(url)
reviews_tab = page.locator('div[data-test-target="reviews-tab"]')
print(f"Reviews tab found: {await reviews_tab.count()}")  # Should be 1

# If 0, TripAdvisor changed the structure. Check the page HTML:
content = await page.content()
print(content[:2000])  # Print first 2000 chars of HTML
```

**Fix:** Update the selector in `extract_restaurant_features()` to match the new HTML.

#### Issue: High CPU/Memory usage; system becomes slow

**Cause:** Playwright keeps many Chromium instances in memory.

**Solution:**
```python
# Reduce concurrent pages
# Don't open multiple browser instances; the script is single-threaded

# Force garbage collection periodically
import gc
gc.collect()  # After every 100 restaurants

# Close unused pages
await page.close()  # If you open extra pages
```

#### Issue: Geopy/Nominatim returns `Connection refused`

**Cause:** Network firewall or DNS issue blocking OpenStreetMap access.

**Debug:**
```bash
# Test connectivity
curl -I https://nominatim.openstreetmap.org/search

# If blocked, try using a proxy:
# Configure geopy with a proxy (advanced; see geopy docs)
```

---

## Performance & Metrics

### Scraping Throughput (v11)

| Phase | Metric | Value |
|---|---|---|
| **Loop 1** (URL extraction) | Pages scanned | ~250 pages |
| | Restaurants per page | ~30 |
| | Total URLs extracted | 7,539 |
| | Duration | 1–2 hours |
| | Throughput | ~1 URL/second (including 5–10s delays) |
| **Loop 2** (Feature extraction) | Restaurants scraped | 7,539 |
| | Duration | 80–120 hours continuous |
| | Throughput | ~25 restaurants/hour (including delays) |
| | Data extracted per restaurant | 11 features + nested reviews |
| **Post-Processing** (Geocoding) | Records geocoded | 7,100 successful |
| | Duration | 3 hours |
| | Throughput | ~2,400 records/hour |

### Output Size

| File | Size | Records |
|---|---|---|
| `tripadvisor_list_restaurant.txt` | 450 KB | 7,539 URLs |
| `tripadvisor_scraper_results.json` | 80 MB | 7,539 restaurants |
| `tripadvisor_checkpoint.json` | < 1 MB | State metadata |
| `tripadvisor_scraper_results_geocoded.json` | 85 MB | 7,539 restaurants + coordinates |

### Network & Rate Limits

| Metric | Value | Notes |
|---|---|---|
| Requests per minute | ~12 | Loop 2 only; includes 5–10s delays |
| Bytes per request | ~200 KB | Average HTML page size |
| Total bandwidth | ~80 GB | Over 80–120 hours (if uncompressed) |
| TripAdvisor API calls | 0 | Pure HTML scraping; no API used |
| IP bans triggered | 0–2 | Rare; depends on ISP and prior behavior |

### Data Quality Metrics

| Field | Coverage | Notes |
|---|---|---|
| `restaurant_name` | 100% | Stable extraction |
| `rating` | 99.8% | ~15 venues unrated |
| `address` | 99.1% | ~66 venues without address |
| `review` | 88.6% | 11.4% have zero reviews or extraction failures |
| `latitude` / `longitude` | 94.2% | After geocoding; 5.8% not found by Nominatim |

---

## Contributing & Development

### Code Style & Conventions

The module follows these conventions:

- **Python Version:** 3.8+ with type hints (PEP 484)
- **Async/Await:** Extensively used; avoid `time.sleep()` in favor of `await page.wait_for_timeout()`
- **Selectors:** Always use `data-automation`, `data-test-target`, or `data-smoke-attr` attributes; avoid CSS classes
- **Logging:** Print-based for simplicity; structured logging via `logging` module not used (can be added)
- **Error Handling:** Broad try-except blocks with `"NaN"` fallback for missing data
- **File I/O:** UTF-8 encoding; `ensure_ascii=False` for JSON

### Adding New Features

**Example: Extract phone number (already implemented)**

```python
async def extract_phone_number(page):
    """Extract venue phone number from contact section."""
    phone_locator = page.locator('a[href^="tel:"]')
    
    if await phone_locator.count() > 0:
        href = await phone_locator.first.get_attribute('href')
        return href.replace("tel:", "").strip() if href else "NaN"
    
    return "NaN"
```

**Guidelines:**
1. Use semantic selectors (stable across deployments)
2. Return `"NaN"` for missing data (not `None`)
3. Add error handling within the function
4. Test on a sample of 10+ restaurants before committing

### Testing

Unit tests are located in `/tests/test_tripadvisor_scraper.py`:

```bash
pytest tests/test_tripadvisor_scraper.py -v

# Test specific function
pytest tests/test_tripadvisor_scraper.py::test_extract_author -v
```

**Test coverage to maintain:**
- Browser detection (multi-browser logic)
- Selector stability (do selectors exist on sample pages?)
- Data extraction (are fields populated correctly?)
- Checkpoint resume (does filtering work?)

### Extending to Other Regions

TripAdvisor has restaurant listings for many cities worldwide. To adapt the scraper:

1. **Change BASE_URL:**
   ```python
   # Milan (g187849)
   BASE_URL = "https://www.tripadvisor.it/Restaurants-g187849-Milan_Lombardy.html"
   
   # Rome (g187791)
   BASE_URL = "https://www.tripadvisor.it/Restaurants-g187791-Rome_Lazio.html"
   
   # Venice (g187870)
   BASE_URL = "https://www.tripadvisor.it/Restaurants-g187870-Venice_Veneto.html"
   ```

2. **Update localization:**
   - Italian month names in date parsing (already handled)
   - Euro currency symbol (change if scraping non-EU regions)

3. **No other changes needed:** Selectors are region-agnostic

---

## References & Further Reading

### Official Documentation

- **Playwright:** https://playwright.dev/python/
- **geopy:** https://geopy.readthedocs.io/
- **Nominatim:** https://nominatim.org/

### Anti-Bot Evasion Techniques

- **Browser Fingerprinting:** https://fingerprint.com/
- **Brave Browser Privacy:** https://brave.com/privacy-features/
- **Chrome DevTools Protocol (CDP):** https://chromedevtools.github.io/devtools-protocol/

### Related Modules in This Project

- **`extract/google_places_api/`** — Parallel data source (venue metadata from Google Places)
- **`extract/thefork_scraper/`** — TheFork (restaurant reservation data)


### Operational Guides

- **IP Management & VPNs**
- **Distributed Scraping:** Use `merge_results.py` to combine outputs from multiple machines

---

## Support & Questions

For issues, questions, or contributions:

1. Check this README and the [Troubleshooting](#troubleshooting) section
2. Review `scraper_logic_v11.md` for architecture details
3. Consult `dataset-schema.md` for data structure questions
4. Open an issue on the project repository with:
   - Python version (`python --version`)
   - OS and browser
   - Error message (full traceback)
   - Reproduction steps


