# Tripadvisor Milan Scraper

Python scraper for Tripadvisor Milan restaurant listing pages. It uses Playwright, reads only listing pages, and writes a normalized JSON dataset aligned with Google, Tripadvisor, and TheFork restaurant datasets.

## What It Collects

The scraper extracts only data visible on Tripadvisor listing cards:

- restaurant name
- rating
- review count
- cuisine type
- price range
- restaurant URL
- source page number

Fields not reliably available from listing pages, such as address, website, phone number, email, opening hours, latitude, longitude, discount, and full reviews, are saved as `null` or `[]` according to the normalized schema.

## Installation

```bash
cd tripadvisor_scraper
pip install -r requirements.txt
python -m playwright install chromium
```

The scraper first tries the installed Chrome browser channel, then Microsoft Edge, then bundled Chromium.

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

Warm up and save a persistent browser session:

```bash
python -m src.main --manual-unlock --headed --user-data-dir output/browser_profile --save-session-only
```

Run with assisted manual unlock:

```bash
python -m src.main --manual-unlock --headed --user-data-dir output/browser_profile
```

If Tripadvisor shows a DataDome or captcha challenge, solve it in the browser window. The scraper waits for restaurant links to appear and then continues automatically.

Resume from the partial JSON after an interruption:

```bash
python -m src.main --manual-unlock --headed --user-data-dir output/browser_profile --resume
```

Useful options:

```text
--max-pages N              Stop after N listing pages.
--delay-seconds N          Delay between listing pages.
--partial-every-pages N    Save partial progress every N processed pages.
--browser-channel NAME     Use chrome, msedge, or chromium.
--headed                   Open a visible browser window.
--user-data-dir PATH       Reuse a persistent browser profile.
--manual-unlock            Wait for manual DataDome or captcha unlock.
--unlock-timeout-seconds N Wait up to N seconds for manual unlock.
--save-session-only        Save the browser session without scraping JSON output.
--resume                   Continue from the existing partial JSON.
--log-level LEVEL          Use INFO, DEBUG, WARNING, or ERROR.
```

## Output

Final JSON:

```text
output/tripadvisor_milan_restaurants_normalized.json
```

Partial progress JSON:

```text
output/tripadvisor_milan_restaurants_normalized_partial.json
```

## Notes

- The scraper never opens individual restaurant detail pages.
- Restaurant links are identified with `a[href*="Restaurant_Review-"]` and filtered to URLs matching `Restaurant_Review-g187849-d<id>-Reviews-`.
- The restaurant URL, stripped of query and fragment parts, is the main deduplication key.
- If a restaurant URL is missing, the fallback key is restaurant name plus address, then restaurant name plus page number.
- The fixed normalized city value is `Milan`.
- Tripadvisor may return a DataDome captcha or block page. In non-interactive mode, the scraper stops with a clear English error. In `--manual-unlock` mode, it keeps the browser open and waits for manual unlock.
