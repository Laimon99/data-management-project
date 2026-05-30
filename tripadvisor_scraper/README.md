# Tripadvisor Milan Scraper

Python scraper for Tripadvisor Milan restaurants. It first collects restaurants from listing pages, deduplicates restaurant URLs, then optionally opens each restaurant detail page to enrich the normalized records.

## What It Collects

Listing pages provide fallback data:

- restaurant URL
- restaurant name
- rating
- review count
- cuisine type
- price range
- photo count when visible
- review snippets when visible
- source page number

Detail pages try to improve:

- full restaurant name and address
- latitude and longitude when explicitly present
- rating and review count
- cuisine type and price range
- discount if exposed
- photo count
- website, phone number, and email when exposed
- opening hours
- review snippets and up to 5 reviews
- `detail_scraped`

Extraction priority is JSON-LD, embedded JSON, visible HTML text, links and attributes, listing fallback data, then `null`.

## Installation

```bash
cd tripadvisor_scraper
pip install -r requirements.txt
python -m playwright install chromium
```

The scraper first tries the installed Chrome browser channel, then Microsoft Edge, then bundled Chromium.

## Execution

Run the full listing + detail scraper:

```bash
python -m src.main
```

Run a small validation sample without overwriting the main output directory:

```bash
python -m src.main --manual-unlock --headed --user-data-dir output/browser_profile --max-pages 1 --max-restaurants 10 --output-dir output/detail_sample
```

Run listing-only mode:

```bash
python -m src.main --no-detail-pages
```

Warm up and save a persistent browser session:

```bash
python -m src.main --manual-unlock --headed --user-data-dir output/browser_profile --save-session-only
```

Resume from the partial JSON after an interruption:

```bash
python -m src.main --manual-unlock --headed --user-data-dir output/browser_profile --resume
```

Run automatic detail retries until every restaurant is complete:

```bash
python -m src.main --auto-detail-until-complete --manual-unlock --headed --user-data-dir output/browser_profile --detail-delay-seconds 10 --detail-batch-size 25
```

Useful options:

```text
--max-pages N                    Stop after N listing pages.
--max-restaurants N              Enrich at most N restaurants.
--delay-seconds N                Delay between listing pages.
--detail-delay-seconds N         Delay between detail pages.
--partial-every-pages N          Save partial progress every N listing pages.
--partial-every-restaurants N    Save partial progress every N enriched restaurants.
--browser-channel NAME           Use chrome, msedge, or chromium.
--headed                         Open a visible browser window.
--user-data-dir PATH             Reuse a persistent browser profile.
--manual-unlock                  Wait for manual DataDome or captcha unlock.
--unlock-timeout-seconds N       Wait up to N seconds for manual unlock.
--save-session-only              Save the browser session without scraping JSON output.
--resume                         Continue from the existing partial JSON.
--auto-detail-until-complete     Retry missing detail pages with cooldowns until complete.
--detail-batch-size N            Reopen the browser after N missing detail pages.
--cooldown-seconds N             Initial cooldown after a blocked detail batch.
--max-cooldown-seconds N         Maximum cooldown after repeated blocked batches.
--cooldown-multiplier N          Multiplier for repeated blocked cooldowns.
--max-auto-detail-cycles N       Maximum automatic retry cycles.
--max-consecutive-detail-failures N
                                 Stop detail scraping after repeated detail failures.
--save-final-incomplete          Write final JSON even if some detail pages are missing.
--output-dir PATH                Save output files in a custom directory.
--no-detail-pages                Skip detail pages.
--log-level LEVEL                Use INFO, DEBUG, WARNING, or ERROR.
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

Validation report:

```text
output/tripadvisor_milan_validation_report.json
```

## Notes

- Restaurant links are identified with `a[href*="Restaurant_Review-"]` and filtered to URLs matching `Restaurant_Review-g187849-d<id>-Reviews-`.
- Tripadvisor offset pagination uses URLs such as `oa30`, `oa60`, and `oa90` when a next link is not reliable.
- The restaurant URL, stripped of query and fragment parts, is the main deduplication key.
- If a detail page fails, listing data is kept and `detail_scraped` is set to `false`.
- In `--auto-detail-until-complete` mode, blocked or failed detail batches are saved, cooled down, and retried from the next missing detail.
- Tripadvisor may return a DataDome captcha or block page. In `--manual-unlock` mode, the scraper keeps the browser open and waits for manual unlock.
- The fixed normalized city value is `Milan`.
