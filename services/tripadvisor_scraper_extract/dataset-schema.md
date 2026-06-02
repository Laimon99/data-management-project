# Dataset Schema — Tripadvisor Scraper (`tripadvisor_scraper_results.json`)

A JSON array where each element is one restaurant scraped from Tripadvisor
(Milan area) by the Playwright scraper in `scraper.py`.
Total records (current run): **~3,608**.

Raw file path: `data/raw/tripadvisor/tripadvisor_scraper_results.json`.

All scraped values are stored **as strings exactly as rendered on the page**
(Italian locale): no numeric parsing, comma decimal separators, currency glyphs,
and parenthesised counts are preserved verbatim. Downstream cleaning is a later
pipeline stage.

---

## Top-level fields

| Field | Type | Coverage | Description |
|---|---|---|---|
| `source_url` | string | 100% | The Tripadvisor URL the record was scraped from. Stamped by the scraper at extraction time. |
| `restaurant_name` | string | 100% | Display name of the venue (e.g. `"Osteria del Balabiott"`). |
| `rating` | string | ~95% | Aggregate rating as displayed, comma decimal (e.g. `"4,3"`). Empty/absent for venues with no rating. |
| `total_review` | string | ~95% | Review count as displayed, including surrounding text (e.g. `"(278 recensioni)"`). |
| `cuisine_type` | string | varies | Cuisine label(s) shown on the page (e.g. `"Italiana"`). |
| `price_range` | string | varies | Price band glyphs as displayed (e.g. `"€€-€€€"`). Validated to a `€`-only band; `"NaN"` when no real price is shown (a sponsored banner is rejected). |
| `number_photo_uploaded` | string | varies | Count of uploaded photos as a string (e.g. `"380"`). |
| `address` | string | ~100% | Full address line (e.g. `"Piazza Vesuvio 13, 20144 Milano Italia"`). |
| `website` | string | varies | Venue's own website URL, when listed. |
| `phone_number` | string | varies | Phone number as displayed (e.g. `"+39 02 2316 3376"`). |
| `email` | string | rare | Contact email, when listed. |
| `working_days_hours` | string | varies | Opening hours flattened into a single string with `and` separators between day/time segments. |
| `review` | list[object] \| `"NaN"` | varies | Up to the reviews captured on the first page. The literal string `"NaN"` when no reviews were extracted. See the `review` object below. |

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
