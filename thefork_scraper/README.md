# TheFork Milan Scraper

Python scraper for TheFork Milan restaurant listing pages. It uses Playwright, reads only listing pages, and writes a normalized JSON dataset aligned with existing Google and Tripadvisor restaurant datasets.

## What It Collects

The scraper extracts only data visible on TheFork listing cards:

- restaurant name
- address
- rating
- review count
- cuisine type
- average price
- visible discount
- restaurant URL
- source page number

Fields not available from listing pages, such as website, phone number, email, opening hours, latitude, longitude, and full reviews, are saved as `null` or `[]` according to the normalized schema.

## Installation

```bash
cd thefork_scraper
pip install -r requirements.txt
python -m playwright install chromium
```

The scraper first tries the installed Chrome browser channel, then Microsoft Edge, then bundled Chromium. This is intentional because TheFork may block bundled Chromium in some environments.

## Execution

Run the full scraper:

```bash
python -m src.main
```

Run a short smoke test:

```bash
python -m src.main --max-pages 1
```

Run with a specific browser channel:

```bash
python -m src.main --browser-channel chrome
```

Useful options:

```text
--max-pages N              Stop after N listing pages.
--delay-seconds N          Delay between listing pages.
--partial-every-pages N    Save partial progress every N processed pages.
--browser-channel NAME     Use chrome, msedge, or chromium.
--headed                   Open a visible browser window.
--log-level LEVEL          Use INFO, DEBUG, WARNING, or ERROR.
```

## Output

Final JSON:

```text
output/thefork_milan_restaurants_normalized.json
```

Partial progress JSON:

```text
output/thefork_milan_restaurants_normalized_partial.json
```

## Notes

- The scraper never opens individual restaurant detail pages.
- Restaurant links are identified with `a[href*="/ristorante/"]` and filtered to URLs matching `/ristorante/<slug>-r<id>`.
- The restaurant URL, stripped of query and fragment parts, is the main deduplication key.
- If a restaurant URL is missing, the fallback key is restaurant name plus address.
- TheFork card text is source data, so Italian cuisine labels and addresses remain as shown on the website.
- The fixed normalized city value is `Milan`.

