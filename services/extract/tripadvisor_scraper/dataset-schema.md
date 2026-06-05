# Dataset Schema — Tripadvisor Scraper (`tripadvisor_scraper_results.json`)

A JSON array where each element is one restaurant scraped from Tripadvisor
(Milan area) by the Playwright scraper in `scraper.py`.
Total records (current run): **7,539**.

Raw file path: `data/raw/tripadvisor/tripadvisor_scraper_results.json`.

All scraped values are stored **as strings exactly as rendered on the page**
(Italian locale): no numeric parsing, comma decimal separators, currency glyphs,
and parenthesised counts are preserved verbatim. Downstream cleaning is a later
pipeline stage.

---

## Top-level fields

| Field | Type | Coverage | Description |
|---|---|---|---|
| `source_url` | string | 100% | The Tripadvisor URL the record was scraped from. Stamped by the scraper at extraction time. All 7,539 URLs are unique and follow the `Restaurant_Review` path pattern. |
| `restaurant_name` | string | 100% | Display name of the venue (e.g. `"Osteria del Balabiott"`). 7,215 unique names — duplicates are chain locations (e.g. McDonald's, La Piadineria). |
| `rating` | string | 99.8% | Aggregate rating as displayed, comma decimal (e.g. `"4,3"`). `"NaN"` for ~15 venues with no rating yet. Needs `.replace(",", ".")` before numeric use. |
| `total_review` | string | 100% | Review count as displayed, including surrounding Italian text (e.g. `"(278 recensioni)"`). 813 venues have zero reviews. Extract the integer with `r"\((\d+)"`. |
| `cuisine_type` | string | 77.7% | Cuisine label(s) shown on the page, comma-separated (e.g. `"Italiana, Pizza"`). 260 unique values. `"NaN"` for 22.3% of venues where Tripadvisor omits the field. |
| `price_range` | string | 67.7% | Price band glyphs as displayed (e.g. `"€€-€€€"`). Only 4 distinct values: `€`, `€€-€€€`, `€€€€`, `NaN`. Validated to `€`-only bands; hotel/sponsored banners are rejected. |
| `number_photo_uploaded` | string | 78.9% | Count of uploaded photos as a string (e.g. `"380"`). `"NaN"` for 21.1% of venues. |
| `address` | string | 99.1% | Full address line (e.g. `"Piazza Vesuvio 13, 20144 Milano Italia"`). 66 venues (0.9%) have `"NaN"` — Tripadvisor did not display an address on those pages. 99.1% contain "Milano". |
| `website` | string | 79.9% | Venue's own website URL, when listed. `"NaN"` for 20.1%. |
| `phone_number` | string | 90.1% | Phone number as displayed (e.g. `"+39 02 2316 3376"`). `"NaN"` for 9.9%. |
| `email` | string | 46.9% | Contact email, when listed. `"NaN"` for 53.1% — most restaurants do not publish an email on Tripadvisor. |
| `working_days_hours` | string | 67.6% | Opening hours flattened into a single string with `and` separators between day/time segments (e.g. `"Domenica: 12.00-15.00 and 19.00-23.00 and Lunedì and ..."`). `"NaN"` for 32.4%. |
| `review` | list[object] \| `"NaN"` | 88.6% | Reviews captured from the first page, stored as a JSON list. The literal string `"NaN"` for 11.4% of venues (zero reviews or scrape failure). See the `review` object below. |

---

## `review` object

Each element of the `review` list. Fields hold page text verbatim.

| Field | Type | Coverage | Description |
|---|---|---|---|
| `author` | object | 100% | Review author. See `author` object below. |
| `title` | string | ~100% | Review title/headline. |
| `text` | string | ~100% | Review body. May end with the `"Scopri di più"` ("read more") expander label appended from the page. |
| `date_of_publication` | string | ~100% | Publication date as displayed, Italian month names (e.g. `"16 maggio 2026"`). |

### `author` object

| Field | Type | Coverage | Description |
|---|---|---|---|
| `nickname` | string | 100% | Author nickname, extracted from the `/Profile/` href. |
| `number_of_contribution` | string | varies | Number of contributions by the author as a string (e.g. `"344"`). |

---

## Checkpoint file (`tripadvisor_checkpoint.json`)

Resume state written by the scraper (and re-emitted by `merge_results.py`).
Raw path: `data/raw/tripadvisor/tripadvisor_checkpoint.json`.

| Field | Type | Coverage | Description |
|---|---|---|---|
| `processed_urls` | list[string] | 100% | URLs already scraped successfully. On startup the scraper skips any URL in this list. After a merge, this is the union of every machine's processed URLs. |
| `failed_urls` | list[string] | 100% | URLs that failed to scrape. After a merge, the union across all machines. |
| `last_update` | string (ISO 8601) | 100% | Local timestamp of the last write (e.g. `"2026-05-30T13:18:28.478770"`). |

---

## Redo list (`redo_urls.txt`)

Plain text, one URL per line — emitted by `merge_results.py`. The master URL
list minus the merged `processed_urls`: exactly the URLs still left to scrape.
