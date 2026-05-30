# Tripadvisor Milan Scraper - Normalized Listing + Detail Pages

## Goal

Create a Python scraper for Tripadvisor Milan restaurants.

Starting URL:

```text
https://www.tripadvisor.it/Restaurants-g187849-Milan_Lombardy.html
```

The scraper must first navigate all listing pages, collect restaurant URLs, and then open each restaurant detail page when `SCRAPE_DETAIL_PAGES = True`.

The final output must be a normalized JSON aligned with Google, Tripadvisor, and TheFork restaurant datasets.

The whole project must be written in English: file names, variables, classes, functions, comments, README, logs, and error messages.

---

## Scraping Strategy

The scraper has two phases.

### Phase 1: Listing pages

Use listing pages to collect:

- restaurant URL;
- restaurant name if visible;
- rating if visible;
- review count if visible;
- cuisine type if visible;
- price range if visible;
- review snippets if visible;
- source listing page number.

### Phase 2: Detail pages

Use detail pages to enrich each record with:

- restaurant name;
- full address;
- latitude;
- longitude;
- rating;
- review count;
- cuisine type;
- price range;
- photo count;
- website;
- phone number;
- email if available;
- working days and hours;
- full reviews or review snippets;
- additional structured metadata.

Only extract values that are explicitly present in the page, structured data, embedded JSON, map data, visible text, or accessible attributes. Do not invent values.

---

## Configuration Requirements

Create a `config.py` file with at least these options:

```python
START_URL = "https://www.tripadvisor.it/Restaurants-g187849-Milan_Lombardy.html"
SCRAPE_DETAIL_PAGES = True
HEADLESS = True
MAX_RESTAURANTS = None
MAX_LISTING_PAGES = None
MAX_REVIEWS_PER_RESTAURANT = 5
DELAY_BETWEEN_LISTING_PAGES_SECONDS = 1.5
DELAY_BETWEEN_DETAIL_PAGES_SECONDS = 2.0
SAVE_PARTIAL_EVERY_N_RESTAURANTS = 25
MAX_CONSECUTIVE_EMPTY_PAGES = 3
OUTPUT_FILE = "output/tripadvisor_milan_restaurants_normalized.json"
PARTIAL_OUTPUT_FILE = "output/tripadvisor_milan_restaurants_normalized_partial.json"
VALIDATION_REPORT_FILE = "output/tripadvisor_milan_validation_report.json"
```

---

## Normalized JSON Schema

Every restaurant record must use this normalized schema initially:

```json
{
  "source": "tripadvisor",
  "source_id": "d8393728",
  "restaurant_name": "Trippa",
  "address": "Via Giorgio Vasari, 1, Milan",
  "city": "Milan",
  "latitude": 45.451234,
  "longitude": 9.176543,
  "rating": 4.5,
  "review_count": 1039,
  "cuisine_type": "Italian, Lombard",
  "price_range": "$$ - $$$",
  "discount": null,
  "photo_count": 250,
  "website": "https://example.com",
  "phone_number": "+39 02 0000 0000",
  "email": null,
  "working_days_hours": null,
  "restaurant_url": "https://www.tripadvisor.it/Restaurant_Review-g187849-d8393728-Reviews-Trippa-Milan_Lombardy.html",
  "review_snippets": ["Excellent dinner and great service."],
  "reviews": [
    {
      "author_name": "Mario",
      "rating": 5,
      "title": "Excellent dinner",
      "text": "Excellent restaurant.",
      "date": "2026-05-20"
    }
  ],
  "scraped_at": "2026-05-29T00:00:00Z",
  "source_page_number": 1,
  "detail_scraped": true
}
```

Use `null` for unavailable scalar fields and `[]` for unavailable array fields. However, do not keep fields that are always null for all restaurants unless all extraction strategies have been tested and documented.

---

## Field Extraction Rules

### `source`

Fixed value: `tripadvisor`.

### `source_id`

Extract from the restaurant URL.

Example:

```text
https://www.tripadvisor.it/Restaurant_Review-g187849-d8393728-Reviews-Trippa-Milan_Lombardy.html
```

Expected:

```text
d8393728
```

Steps:

1. search URL path for pattern `-d<digits>-`;
2. store the value with the `d` prefix;
3. fallback to a stable URL slug or URL hash.

### `restaurant_name`

Extraction priority:

1. JSON-LD `name` from detail page;
2. embedded JSON state containing restaurant name;
3. visible main heading on detail page;
4. listing card name;
5. `null`.

Validation rules:

- remove ranking prefixes such as `30. Masayume`;
- do not store generic labels;
- do not store review titles as restaurant names.

### `address`

Extraction priority:

1. JSON-LD `address.streetAddress` or full `address`;
2. embedded JSON location/address;
3. visible detail-page address;
4. listing card address if visible;
5. `null`.

Do not infer the address from the restaurant name.

### `city`

Fixed value: `Milan`.

### `latitude`

Extraction priority:

1. JSON-LD `geo.latitude`;
2. embedded JSON state containing latitude;
3. map data inside scripts;
4. map links containing coordinates;
5. data attributes containing coordinates;
6. `null`.

Rules:

- convert to float;
- do not geocode addresses unless a separate geocoding step is explicitly added;
- do not invent coordinates;
- if always null in tests, inspect at least 2 detail pages, JSON-LD, embedded JSON, and map-related scripts before deciding it is unavailable.

### `longitude`

Same strategy as `latitude`, using longitude fields.

### `rating`

Extraction priority:

1. JSON-LD `aggregateRating.ratingValue`;
2. embedded JSON rating field;
3. visible detail-page rating;
4. listing card rating;
5. `null`.

Normalization:

```text
"4,7" -> 4.7
"4.7" -> 4.7
```

Tripadvisor ratings are on a 5-point scale. Do not convert them to a 10-point scale.

### `review_count`

Extraction priority:

1. JSON-LD `aggregateRating.reviewCount`;
2. embedded JSON review count;
3. visible detail-page review count;
4. listing card review count;
5. `null`.

Normalization examples:

```text
"(1,039 reviews)" -> 1039
"(1.039 recensioni)" -> 1039
"(278 recensioni)" -> 278
```

### `cuisine_type`

Extraction priority:

1. structured data cuisine/category;
2. embedded JSON cuisine/tags/restaurant type;
3. visible detail-page cuisine/category text;
4. listing card cuisine text;
5. `null`.

Do not store price range inside `cuisine_type`.

### `price_range`

Extraction priority:

1. structured data field such as `priceRange`;
2. embedded JSON price fields;
3. visible detail-page price text;
4. listing card price range;
5. `null`.

Recognized patterns:

```text
$
$$ - $$$
$$$$
€
€€-€€€
€€ - €€€
€€€
```

If cuisine and price are merged, split them.

Example:

```text
Japanese, Asian$$ - $$$
```

Expected:

```json
{"cuisine_type": "Japanese, Asian", "price_range": "$$ - $$$"}
```

### `discount`

Tripadvisor usually does not expose restaurant discounts.

Extraction priority:

1. visible offer/discount labels if present;
2. embedded offer fields if present;
3. `null`.

If always null after validation, this field may be removed and documented.

### `photo_count`

Extraction priority:

1. detail-page visible photo/gallery counter;
2. embedded JSON photo/image array length;
3. number of unique restaurant image URLs found in the detail page;
4. listing visible photo count if available;
5. `null`.

Rules:

- count unique restaurant image URLs if an image array exists;
- do not count logos, icons, avatars, tracking pixels, or unrelated images;
- if uncertain, set `null`.

### `website`

Extraction priority:

1. official website button/link visible on detail page;
2. external links not pointing to Tripadvisor;
3. structured data `sameAs` or `url` only if it points to the official restaurant website;
4. embedded JSON website field;
5. `null`.

Rules:

- do not use the Tripadvisor restaurant URL as `website`;
- ignore Tripadvisor internal links, ads, and unrelated tracking links.

### `phone_number`

Extraction priority:

1. visible phone number on detail page;
2. `tel:` links;
3. embedded JSON phone field;
4. structured data telephone field;
5. `null`.

### `email`

Extraction priority:

1. visible email text;
2. `mailto:` links;
3. embedded JSON email field;
4. `null`.

If always null after validation, this field may be removed and documented.

### `working_days_hours`

Extraction priority:

1. structured data `openingHours` or `openingHoursSpecification`;
2. embedded JSON opening hours;
3. visible detail-page opening hours section;
4. `null`.

Format must be consistent across all records: raw string, dictionary by weekday, or list of intervals.

### `restaurant_url`

Absolute Tripadvisor detail URL.

Rules:

- normalize to absolute URL;
- remove tracking query parameters where possible;
- keep canonical URL if present.

### `review_snippets`

Short review snippets visible in listing cards or detail pages.

Extraction priority:

1. listing card snippets;
2. detail-page review highlights;
3. `[]`.

These are not full reviews.

### `reviews`

Full or semi-full reviews from the detail page.

Extraction priority:

1. detail-page review cards;
2. embedded JSON reviews array;
3. structured data reviews;
4. `[]`.

Each review must use:

```json
{
  "author_name": null,
  "rating": null,
  "title": null,
  "text": null,
  "date": null
}
```

Rules:

- collect at most `MAX_REVIEWS_PER_RESTAURANT`;
- do not click infinite review pagination unless explicitly implemented;
- skip empty reviews;
- deduplicate reviews;
- do not store snippets as full reviews unless metadata is present.

### `scraped_at`

UTC ISO 8601 timestamp generated when the record is saved.

### `source_page_number`

Listing page number where the restaurant URL was first discovered.

### `detail_scraped`

`true` if the detail page was opened and parsed successfully, otherwise `false`.

---

## Listing Page Extraction

Do not rely on generated CSS classes as primary selectors.

Preferred strategy:

1. wait for content to load;
2. find restaurant links using `a[href*="/Restaurant_Review-"]`;
3. filter only real restaurant detail URLs;
4. ignore footer, ads, FAQ, hotel, attraction, and unrelated links;
5. normalize each link to absolute URL;
6. get the closest visible restaurant card/container;
7. extract visible text from the container;
8. parse listing fallback fields.

---

## Listing Pagination

Tripadvisor often uses offset-style pagination URLs.

Possible pattern:

```text
https://www.tripadvisor.it/Restaurants-g187849-oa30-Milan_Lombardy.html
https://www.tripadvisor.it/Restaurants-g187849-oa60-Milan_Lombardy.html
https://www.tripadvisor.it/Restaurants-g187849-oa90-Milan_Lombardy.html
```

Preferred strategy:

1. first try to detect and click the visible `Next` / `Successivo` link;
2. if unreliable, generate URLs using the `oa{offset}` pattern;
3. increment offset by 30;
4. stop when no new restaurant URLs are found.

Safety stops:

- no next page;
- no new restaurants;
- repeated empty pages;
- repeated timeouts;
- `MAX_LISTING_PAGES` reached;
- detected maximum result count reached.

---

## Detail Page Extraction

For each restaurant URL:

1. open the detail page;
2. wait for network idle or a stable page state;
3. parse JSON-LD scripts;
4. parse embedded JSON state scripts;
5. parse visible detail sections;
6. parse image/gallery data;
7. parse reviews;
8. merge detail data with listing fallback data.

Priority:

```text
detail structured data > detail embedded JSON > detail visible text > listing fallback > null
```

---

## Validation and Debugging Policy

Codex must implement a validation step. It must not simply scrape and assume the output is correct.

After scraping a small sample, for example 10 to 20 restaurants, generate a field coverage report:

```json
{
  "total_records": 20,
  "field_coverage": {
    "restaurant_name": {"non_null": 20, "null": 0, "coverage_pct": 100},
    "latitude": {"non_null": 13, "null": 7, "coverage_pct": 65},
    "website": {"non_null": 0, "null": 20, "coverage_pct": 0}
  }
}
```

Save it to:

```text
output/tripadvisor_milan_validation_report.json
```

If a field is always null or always empty across the sample, Codex must:

1. inspect the HTML of at least 2 detail pages;
2. inspect JSON-LD scripts;
3. inspect embedded JSON scripts;
4. inspect visible text around likely labels;
5. try an alternative extraction strategy;
6. log what was tried;
7. only after these attempts, decide whether the field is unavailable.

If a field remains always null after all reasonable attempts, Codex may remove it from the final schema, but only after documenting the reason in the validation report.

Do not keep useless fields that are null for every restaurant. Keep fields that are sometimes available and sometimes null.

---

## Output Files

Final output:

```text
output/tripadvisor_milan_restaurants_normalized.json
```

Partial output:

```text
output/tripadvisor_milan_restaurants_normalized_partial.json
```

Validation report:

```text
output/tripadvisor_milan_validation_report.json
```

---

## Recommended Project Structure

```text
tripadvisor_scraper/
├── README.md
├── SCRAPER_SPEC.md
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── listing_scraper.py
│   ├── detail_scraper.py
│   ├── parser.py
│   ├── validators.py
│   ├── storage.py
│   └── models.py
└── output/
    └── .gitkeep
```

---

## Final Codex Requirements

Codex must:

1. implement listing scraping;
2. implement detail scraping;
3. implement normalized output;
4. implement partial saving;
5. implement validation reports;
6. test on a small sample first;
7. verify that fields are not all null;
8. debug fields that are always null;
9. remove fields only if they remain unavailable after documented attempts;
10. write a README in English;
11. report fragile points at the end.
