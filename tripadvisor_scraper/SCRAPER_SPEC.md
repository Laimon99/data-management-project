# Tripadvisor Milan Scraper Specification

## Goal

Create a Python 3.11+ scraper that collects restaurants from the Tripadvisor Milan listing pages and saves a normalized JSON file compatible with existing Google, Tripadvisor, and TheFork restaurant datasets.

Start URL:

```text
https://www.tripadvisor.it/Restaurants-g187849-Milan_Lombardy.html
```

The scraper must not open individual restaurant detail pages. It must collect only information visible on listing pages and navigate through all listing pages until there are no more pages to process.

## Output Files

Final output:

```text
output/tripadvisor_milan_restaurants_normalized.json
```

Partial progress output:

```text
output/tripadvisor_milan_restaurants_normalized_partial.json
```

## Normalized Schema

Each restaurant record must use this schema:

```json
{
  "source": "tripadvisor",
  "source_id": "d8393728",
  "restaurant_name": "Trippa",
  "address": null,
  "city": "Milan",
  "latitude": null,
  "longitude": null,
  "rating": 4.5,
  "review_count": 1039,
  "cuisine_type": "Italian, Lombard",
  "price_range": "$$ - $$$",
  "discount": null,
  "website": null,
  "phone_number": null,
  "email": null,
  "working_days_hours": null,
  "restaurant_url": "https://www.tripadvisor.it/Restaurant_Review-g187849-d8393728-Reviews-Trippa-Milan_Lombardy.html",
  "reviews": [],
  "scraped_at": "2026-05-29T00:00:00Z",
  "source_page_number": 1
}
```

## Field Mapping

- `source`: fixed value `tripadvisor`.
- `source_id`: extracted from the restaurant URL, for example `d8393728`.
- `restaurant_name`: visible card name with ranking prefixes removed.
- `address`: visible address line only, otherwise `null`.
- `city`: fixed value `Milan`.
- `latitude`: `null`.
- `longitude`: `null`.
- `rating`: visible decimal rating normalized to `float`.
- `review_count`: visible review count normalized to `int`.
- `cuisine_type`: visible cuisine label, split from price when possible.
- `price_range`: visible price range, such as `$`, `$$ - $$$`, `$$$$`, or euro equivalents.
- `discount`: `null`.
- `website`: `null`.
- `phone_number`: `null`.
- `email`: `null`.
- `working_days_hours`: `null`.
- `restaurant_url`: absolute Tripadvisor restaurant URL stripped of query and fragment parts.
- `reviews`: empty list.
- `scraped_at`: UTC ISO 8601 timestamp generated during scraping.
- `source_page_number`: listing page number where the restaurant was found.

## Selectors And Page Strategy

Avoid generated CSS classes.

Primary restaurant selector:

```css
a[href*="Restaurant_Review-"]
```

Filter links to Milan restaurant review URLs matching:

```text
Restaurant_Review-g187849-d<id>-Reviews-
```

From each link, climb to the nearest visible ancestor with restaurant-card signals such as rating, review count, cuisine text, or price text.

## Pagination

Tripadvisor commonly uses offset URLs:

```text
https://www.tripadvisor.it/Restaurants-g187849-oa30-Milan_Lombardy.html
https://www.tripadvisor.it/Restaurants-g187849-oa60-Milan_Lombardy.html
https://www.tripadvisor.it/Restaurants-g187849-oa90-Milan_Lombardy.html
```

The scraper should:

- process the first page without an offset;
- prefer a detected next link if one is rendered;
- otherwise generate offset URLs in blocks of 30 results;
- stop on repeated URLs, detected result count reached, no new records, or repeated empty pages.

## Deduplication

Use `restaurant_url` as the primary deduplication key.

If `restaurant_url` is missing, use:

```text
restaurant_name + address
```

If both URL and address are unavailable, use:

```text
restaurant_name + source_page_number
```

## Safety Requirements

- Handle cookie popups if present.
- Log page-by-page progress.
- Detect DataDome or captcha blocks.
- Support assisted manual unlock through a persistent browser profile.
- Handle timeouts safely.
- Save partial progress every few pages and at the end.
- Use a small delay between pages.
- Keep output schema stable even when some fields are unavailable.

## Assisted Manual Unlock

Tripadvisor may block automated browsers with DataDome before restaurant cards render. The scraper supports a low-manual workflow that does not bypass the challenge automatically:

```bash
python -m src.main --manual-unlock --headed --user-data-dir output/browser_profile --save-session-only
```

When a challenge appears, solve it in the browser window. The scraper waits until restaurant links are visible, then saves the browser profile session. A full run can reuse the same profile:

```bash
python -m src.main --manual-unlock --headed --user-data-dir output/browser_profile
```

If DataDome appears again during pagination, the scraper waits for another manual unlock and then resumes from the current listing page.
