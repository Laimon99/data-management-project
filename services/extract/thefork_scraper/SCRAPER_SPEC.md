# TheFork Milan Scraper - Normalized Listing + Detail Pages

## Goal

Create a Python scraper for TheFork Milan restaurants.

Starting URL:

```text
https://www.thefork.it/ristoranti/milano-c348156?cc=17176-c38&gad_source=1&gad_campaignid=8361461667&gclid=CjwKCAjw8uTQBhAdEiwAVvtJyuytSBG4Ly5PzeXRIz0hmBsi4Y0osJXr09YduTdbXMVxXZl2PldaIRoC-AoQAvD_BwE
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
- address if visible;
- rating if visible;
- review count if visible;
- cuisine type if visible;
- price range / average price if visible;
- discount if visible;
- photo count if visible in listing carousel labels;
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
- discount;
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
START_URL = "https://www.thefork.it/ristoranti/milano-c348156?cc=17176-c38&gad_source=1&gad_campaignid=8361461667&gclid=CjwKCAjw8uTQBhAdEiwAVvtJyuytSBG4Ly5PzeXRIz0hmBsi4Y0osJXr09YduTdbXMVxXZl2PldaIRoC-AoQAvD_BwE"
SCRAPE_DETAIL_PAGES = True
HEADLESS = True
MAX_RESTAURANTS = None
MAX_LISTING_PAGES = None
MAX_REVIEWS_PER_RESTAURANT = 5
DELAY_BETWEEN_LISTING_PAGES_SECONDS = 1.5
DELAY_BETWEEN_DETAIL_PAGES_SECONDS = 2.0
SAVE_PARTIAL_EVERY_N_RESTAURANTS = 25
MAX_CONSECUTIVE_EMPTY_PAGES = 3
OUTPUT_FILE = "data/raw/thefork/thefork_milan_restaurants_normalized.json"
PARTIAL_OUTPUT_FILE = "data/raw/thefork/thefork_milan_restaurants_normalized_partial.json"
VALIDATION_REPORT_FILE = "data/raw/thefork/thefork_milan_validation_report.json"
```

---

## Normalized JSON Schema

Every restaurant record must use this normalized schema initially:

```json
{
  "source": "thefork",
  "source_id": "drinkiamo-bistrot-r801007",
  "restaurant_name": "Drinkiamo Bistrot",
  "address": "Via Imperia, 13, Milano",
  "city": "Milan",
  "latitude": 45.451234,
  "longitude": 9.176543,
  "rating": 9.4,
  "review_count": 1088,
  "cuisine_type": "American",
  "price_range": "15 €",
  "discount": "Sconti fino al 30%",
  "photo_count": 12,
  "website": null,
  "phone_number": null,
  "email": null,
  "working_days_hours": null,
  "restaurant_url": "https://www.thefork.it/ristorante/drinkiamo-bistrot-r801007",
  "review_snippets": ["Pasta buonissima e fresca come fatta dalla nonna."],
  "reviews": [
    {
      "author_name": "Mario",
      "rating": 10,
      "title": null,
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

Fixed value: `thefork`.

### `source_id`

Extract from the restaurant URL.

Example:

```text
https://www.thefork.it/ristorante/drinkiamo-bistrot-r801007
```

Expected:

```text
drinkiamo-bistrot-r801007
```

Steps:

1. remove query parameters and fragments;
2. take the last URL path segment;
3. store it as `source_id`;
4. fallback to a stable URL hash if needed.

### `restaurant_name`

Extraction priority:

1. JSON-LD `name` from detail page;
2. embedded JSON state containing restaurant name;
3. visible main heading on detail page;
4. listing card name;
5. `null`.

Validation rules:

- do not store generic labels such as `Reviews`, `Menu`, `Book`, `Photos`;
- do not store review titles as restaurant names.

### `address`

Extraction priority:

1. JSON-LD `address.streetAddress` or full `address`;
2. embedded JSON location/address;
3. visible detail-page address;
4. listing card address;
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
"9,4" -> 9.4
"9.4" -> 9.4
```

TheFork ratings are on a 10-point scale. Do not convert them to a 5-point scale.

### `review_count`

Extraction priority:

1. JSON-LD `aggregateRating.reviewCount`;
2. embedded JSON review count;
3. visible detail-page review count;
4. listing card review count;
5. `null`.

Normalization examples:

```text
"(1088)" -> 1088
"1.088 recensioni" -> 1088
"1,088 reviews" -> 1088
```

### `cuisine_type`

Extraction priority:

1. structured data cuisine/category;
2. embedded JSON cuisine/tags/restaurant type;
3. visible detail-page cuisine/category text;
4. listing card cuisine text;
5. `null`.

Do not store price range or discount inside `cuisine_type`.

### `price_range`

Extraction priority:

1. JSON-LD or structured field such as `priceRange`;
2. embedded JSON price fields;
3. visible detail-page price text;
4. listing card average price, for example `Prezzo medio 15 €`;
5. `null`.

Normalization examples:

```text
"Prezzo medio 15 €" -> "15 €"
"Average price €35" -> "35 €"
```

### `discount`

Extraction priority:

1. listing card discount text;
2. detail-page discount/offer text;
3. embedded JSON discount/offer fields;
4. `null`.

Examples:

```text
Sconti fino al 30%
20% off food
```

### `photo_count`

Extraction priority:

1. detail-page visible photo/gallery counter;
2. embedded JSON image/photo array length;
3. listing carousel label such as `Slide 1 di 12`;
4. number of unique restaurant image URLs found in the detail page;
5. `null`.

Rules:

- count unique restaurant image URLs if an array exists;
- do not count logos, icons, avatars, tracking pixels, or unrelated images;
- if uncertain, set `null`.

### `website`

Extraction priority:

1. visible official website link on detail page;
2. structured data `sameAs` or `url` only if it points to the official restaurant website and not TheFork;
3. embedded JSON official website field;
4. `null`.

Rules:

- do not use the TheFork restaurant URL as `website`;
- if only TheFork URLs are found, keep `website` as `null`.

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

Absolute TheFork detail URL.

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
- deduplicate reviews.

### `scraped_at`

UTC ISO 8601 timestamp generated when the record is saved.

### `source_page_number`

Listing page number where the restaurant URL was first discovered.

### `detail_scraped`

`true` if the detail page was opened and parsed successfully, otherwise `false`.

---

## Listing Page Extraction

TheFork uses dynamically generated CSS classes. Do not rely on `.css-*` classes as primary selectors.

Preferred strategy:

1. wait for content to load;
2. find restaurant links using `a[href*="/ristorante/"]`;
3. filter only real restaurant detail URLs;
4. ignore footer, filters, navigation, and unrelated links;
5. normalize each link to absolute URL;
6. get the closest visible card/container;
7. extract visible text from the container;
8. parse listing fallback fields.

---

## Listing Pagination

Preferred strategy:

1. detect the next-page button/link using text, role, or `aria-label`;
2. click it if reliable;
3. otherwise infer page URLs if TheFork exposes a stable page query parameter;
4. stop when no new restaurant URLs are found or no next page exists.

Safety stops:

- no next page;
- no new restaurants;
- repeated empty pages;
- repeated timeouts;
- `MAX_LISTING_PAGES` reached.

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
data/raw/thefork/thefork_milan_validation_report.json
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
data/raw/thefork/thefork_milan_restaurants_normalized.json
```

Partial output:

```text
data/raw/thefork/thefork_milan_restaurants_normalized_partial.json
```

Validation report:

```text
data/raw/thefork/thefork_milan_validation_report.json
```

---

## Recommended Project Structure

> This reflects the original standalone design. In this repo the scraper lives
> at `services/extract/thefork_scraper/` and is run via
> `uv run thefork-scraper-extract`; see the service `README.md` for the current
> layout and invocation.

```text
thefork_scraper/
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
