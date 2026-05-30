# TheFork Milan Scraper Specification

## Goal

Create a Python 3.11+ scraper that collects restaurants from the TheFork Milan listing pages and saves a normalized JSON file compatible with existing Google and Tripadvisor restaurant datasets.

Start URL:

```text
https://www.thefork.it/ristoranti/milano-c348156
```

The scraper must not open individual restaurant detail pages. It must collect only information visible on listing pages and navigate through all listing pages until there are no more new pages to process.

## Output Files

Final output:

```text
output/thefork_milan_restaurants_normalized.json
```

Partial progress output:

```text
output/thefork_milan_restaurants_normalized_partial.json
```

## Normalized Schema

Each restaurant record must use this schema:

```json
{
  "source": "thefork",
  "source_id": "drinkiamo-bistrot-r801007",
  "restaurant_name": "Drinkiamo Bistrot",
  "address": "Via Imperia, 13, Milano",
  "city": "Milan",
  "latitude": null,
  "longitude": null,
  "rating": 9.4,
  "review_count": 1088,
  "cuisine_type": "Americano",
  "price_range": "15 EUR",
  "discount": "Sconti fino al 30%",
  "website": null,
  "phone_number": null,
  "email": null,
  "working_days_hours": null,
  "restaurant_url": "https://www.thefork.it/ristorante/drinkiamo-bistrot-r801007",
  "reviews": [],
  "scraped_at": "2026-05-29T00:00:00Z",
  "source_page_number": 1
}
```

The real `price_range` value is parsed from TheFork card text and may contain the euro symbol exactly as shown by the website.

## Field Mapping

- `source`: fixed value `thefork`.
- `source_id`: extracted from the restaurant URL path, for example `drinkiamo-bistrot-r801007`.
- `restaurant_name`: visible card name, preferably from the restaurant link accessibility label.
- `address`: first visible card line containing `Milano`.
- `city`: fixed value `Milan`.
- `latitude`: `null`.
- `longitude`: `null`.
- `rating`: visible decimal rating normalized to `float`.
- `review_count`: visible parenthesized review count normalized to `int`.
- `cuisine_type`: visible cuisine label between address/rating/review lines and average price.
- `price_range`: value after `Prezzo medio`, normalized without the label.
- `discount`: visible discount line such as `Sconti fino al 20%`, or `null`.
- `website`: `null`.
- `phone_number`: `null`.
- `email`: `null`.
- `working_days_hours`: `null`.
- `restaurant_url`: absolute restaurant URL stripped of query and fragment parts.
- `reviews`: empty list.
- `scraped_at`: UTC ISO 8601 timestamp generated during scraping.
- `source_page_number`: listing page number where the restaurant was found.

## Selectors And Page Strategy

Avoid generated CSS classes such as `.css-*`.

Primary restaurant selector:

```css
a[href*="/ristorante/"]
```

Filter links to paths matching:

```text
/ristorante/<slug>-r<id>
```

Use the restaurant anchor text as the primary card text because current TheFork listing cards expose the whole card through the link. If that text is incomplete, climb to a nearby parent with a small number of restaurant links and parse that visible text.

## Pagination

Pagination uses the query parameter `p`:

```text
https://www.thefork.it/ristoranti/milano-c348156?p=2
```

The scraper should:

- process page 1 without `p`;
- process subsequent pages by incrementing `p`;
- detect the approximate last page from pagination controls or total restaurant count;
- stop if the page number exceeds the detected max page;
- stop if too many consecutive pages produce no new restaurants.

## Deduplication

Use `restaurant_url` as the primary deduplication key after stripping query and fragment parts.

If `restaurant_url` is missing, use:

```text
restaurant_name + address
```

## Safety Requirements

- Handle cookie popups if present.
- Log page-by-page progress.
- Handle timeouts safely.
- Save partial progress every few pages and at the end.
- Use a small delay between pages.
- Keep output schema stable even when some fields are unavailable.
- Prefer installed Chrome or Edge before bundled Chromium, because TheFork may block bundled Chromium in some environments.

