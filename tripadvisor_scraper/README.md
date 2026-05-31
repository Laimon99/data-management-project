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
python -m src.main --auto-detail-until-complete --manual-unlock --headed --user-data-dir output/browser_profile --detail-delay-seconds 5 --detail-batch-size 50
```

Run a direct-IP calibration before buying or assigning proxies:

```bash
python -m src.main --calibrate-detail-blocks --manual-unlock --headed --user-data-dir output/browser_profile --calibration-max-records 50 --calibration-delay-seconds 5,10,20
```

Run the same calibration with a proxy list:

```bash
python -m src.main --calibrate-detail-blocks --manual-unlock --headed --user-data-dir output/browser_profile --proxy-list proxy_list.txt --calibration-max-records 50 --calibration-delay-seconds 5,10,20
```

Run the final scraper through rotating proxies:

```bash
python -m src.main --auto-detail-until-complete --manual-unlock --headed --user-data-dir output/browser_profile --proxy-list proxy_list.txt --detail-delay-seconds 5 --detail-batch-size 50
```

Recommended proxy strategy for postponing IP blocks:

```bash
python -m src.main --proxy-round-robin --manual-unlock --headed --user-data-dir output/browser_profile --proxy-list proxy_list.txt --restaurants-per-proxy-turn 1 --proxy-min-rest-seconds 90 --proxy-max-failed-turns 3 --detail-delay-min-seconds 4 --detail-delay-max-seconds 9 --proxy-turn-jitter-seconds 3 --human-detail-scroll
```

This mode rotates after a small number of detail pages, gives each proxy a rest window before reuse, keeps one persistent browser profile per proxy, and saves a proxy progress report after every turn. If DataDome appears and `--manual-unlock` is enabled, solve it in the browser window and the scraper resumes from the same queue.

Optional Brave run:

```bash
python -m src.main --proxy-round-robin --manual-unlock --headed --user-data-dir output/browser_profile --proxy-list proxy_list.txt --browser-executable-path "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --restaurants-per-proxy-turn 1 --proxy-min-rest-seconds 90 --detail-delay-min-seconds 4 --detail-delay-max-seconds 9 --human-detail-scroll
```

Useful options:

```text
--max-pages N                    Stop after N listing pages.
--max-restaurants N              Enrich at most N restaurants.
--delay-seconds N                Delay between listing pages.
--detail-delay-seconds N         Delay between detail pages.
--detail-delay-min-seconds N     Minimum random delay between detail pages.
--detail-delay-max-seconds N     Maximum random delay between detail pages.
--human-detail-scroll            Lightly scroll detail pages before extraction.
--partial-every-pages N          Save partial progress every N listing pages.
--partial-every-restaurants N    Save partial progress every N enriched restaurants.
--browser-channel NAME           Use chrome, msedge, or chromium.
--browser-executable-path PATH   Use an explicit browser executable, for example Brave.
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
--proxy-list PATH                Read one proxy URL per line and rotate it by browser batch.
--proxy-server URL               Use one proxy server, for example http://host:port.
--proxy-username TEXT            Username for --proxy-server.
--proxy-password TEXT            Password for --proxy-server.
--proxy-round-robin              Rotate proxies after a small number of detail pages.
--restaurants-per-proxy-turn N   Detail pages attempted before switching proxy.
--proxy-min-rest-seconds N       Minimum rest time before the same proxy is reused.
--proxy-max-failed-turns N       Retire a proxy after repeated failed turns.
--proxy-turn-jitter-seconds N    Add random delay between proxy turns.
--include-direct-ip-after-proxies
                                 Use the direct IP after all proxies are retired.
--calibrate-detail-blocks        Run block-limit calibration and save reports.
--calibration-output-dir PATH    Save calibration reports and sample records.
--calibration-max-records N      Test at most N missing detail records per calibration run.
--calibration-delay-seconds CSV  Test comma-separated delays, for example 10,20,30.
--calibration-batch-size N       Max records attempted in one calibration session.
--calibration-time-budget-hours N
                                 Target scraping time used for proxy estimates.
--calibration-max-proxies N      Max proxies considered by calibration estimates.
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

Calibration report:

```text
output/calibration/tripadvisor_block_calibration_report.json
```

Proxy progress report:

```text
output/tripadvisor_proxy_progress_report.json
```

## Notes

- Restaurant links are identified with `a[href*="Restaurant_Review-"]` and filtered to URLs matching `Restaurant_Review-g187849-d<id>-Reviews-`.
- Tripadvisor offset pagination uses URLs such as `oa30`, `oa60`, and `oa90` when a next link is not reliable.
- The restaurant URL, stripped of query and fragment parts, is the main deduplication key.
- If a detail page fails, listing data is kept and `detail_scraped` is set to `false`.
- In `--auto-detail-until-complete` mode, blocked or failed detail batches are saved, cooled down, and retried from the next missing detail.
- In `--proxy-round-robin` mode, `--max-restaurants` limits only the work queue and does not truncate the partial JSON.
- Tripadvisor may return a DataDome captcha or block page. In `--manual-unlock` mode, the scraper keeps the browser open and waits for manual unlock.
- When proxies are used with a persistent profile, the scraper isolates profiles per proxy under `output/browser_profiles/`.
- If every proxy returns HTTP 403 immediately, the pool is already blocked or too low quality; let it cool down or replace it before a full run.
- Current calibration with the direct IP completed 50 of 50 detail pages at 5 seconds delay with no DataDome block. The default detail batch is therefore 50.
- With a 20 hour budget and 15 minute cooldowns, the conservative report estimates 3 proxies as the mathematical minimum and 4 proxies as the recommended margin target.
- Proxy credentials should stay in a local `proxy_list.txt` or environment-specific file; those files are ignored by Git.
- Calibration outputs are kept in `output/calibration/` so the experiments can be reviewed later.
- The fixed normalized city value is `Milan`.
