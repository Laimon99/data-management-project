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
- social links separately from official website links
- opening hours as both display text and structured data when exposed
- review snippets and configurable reviews per restaurant
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

Recommended Brave automation profile:

```bash
python -m src.main --brave-automation-profile --auto-detail-until-complete --detail-delay-min-seconds 5 --detail-delay-max-seconds 10 --detail-batch-size 25 --human-detail-scroll
```

On Windows this uses `C:\tmp\tripadvisor_brave_automation_profile` by default, so Chromium profile files stay outside OneDrive and long project paths. It runs headed with Brave, warms up the profile on the listing URL, then continues missing detail pages from the partial JSON.

Launch multiple Brave proxy profiles and run CDP detail workers in parallel:

```bash
python -m src.main --cdp-parallel-proxies --proxy-list proxy_list.txt --parallel-workers 3 --parallel-base-port 9420 --detail-delay-min-seconds 5 --detail-delay-max-seconds 10 --max-consecutive-detail-failures 3 --partial-every-restaurants 5 --human-detail-scroll
```

This command opens one Brave profile per worker, one proxy per profile, and one local CDP port per profile. Authenticated proxies are handled by a generated local Chrome extension inside each profile directory, so proxy credentials do not appear in worker commands. The launcher pauses before scraping: check every Tripadvisor window, solve cookies/captcha/proxy prompts if needed, then press Enter in the terminal.

Each worker writes a separate partial under `output/runs/cdp_parallel/run_YYYYMMDD_HHMMSS/`. At the end, the launcher backs up the existing `output/tripadvisor_milan_restaurants_normalized_partial.json`, merges that original partial plus all fresh worker partials, and writes a merge audit next to the partial as `tripadvisor_milan_restaurants_normalized_partial.parallel_merge_report.json`. If every restaurant has `detail_scraped=true`, it also writes `output/tripadvisor_milan_restaurants_enriched.json`.

If `output/tripadvisor_milan_restaurants_normalized_partial.json` does not exist yet but `output/tripadvisor_milan_restaurants_normalized.json` does, a real parallel run creates the partial from the existing listing-only dataset before launching workers.

The worker split is based on missing detail records first, then sharding. This means already enriched restaurants are skipped before work is divided, reducing duplicate work between parallel profiles.

Run listing collection and parallel detail enrichment from a clean output directory with one command:

```bash
python -m src.main --brave-automation-profile --cdp-parallel-proxies --parallel-build-listing-if-missing --proxy-list proxy_list.txt --parallel-workers 5 --distributed-slot-count 10 --distributed-slot-start 0 --parallel-base-port 9460 --parallel-profile-root C:\tmp\tripadvisor_cdp_proxy_profiles --user-data-dir C:\tmp\tripadvisor_listing_profile --detail-delay-min-seconds 6 --detail-delay-max-seconds 12 --max-consecutive-detail-failures 5 --partial-every-restaurants 5 --human-detail-scroll --log-level INFO
```

This command first creates `output/tripadvisor_milan_restaurants_normalized_partial.json` if it is missing, using listing pages only. It then launches the parallel Brave proxy profiles, enriches the missing details, and automatically merges worker outputs back into the partial. Use short profile paths such as `C:\tmp\...` on Windows to avoid long-path browser profile issues.

Distributed runs across multiple PCs use the same pending-first split, but with a global slot count. For example, if this Windows PC runs 5 profiles and a Mac Mini runs 3 profiles, use 8 total slots:

Windows PC:

```bash
python -m src.main --cdp-parallel-proxies --proxy-list proxy_list.txt --parallel-workers 5 --distributed-slot-count 8 --distributed-slot-start 0 --parallel-base-port 9460 --detail-delay-min-seconds 6 --detail-delay-max-seconds 12 --max-consecutive-detail-failures 5 --partial-every-restaurants 5 --human-detail-scroll
```

Mac Mini:

```bash
python -m src.main --cdp-parallel-proxies --proxy-list proxy_list.txt --parallel-workers 3 --distributed-slot-count 8 --distributed-slot-start 5 --parallel-base-port 9460 --detail-delay-min-seconds 6 --detail-delay-max-seconds 12 --max-consecutive-detail-failures 5 --partial-every-restaurants 5 --human-detail-scroll
```

`--distributed-slot-start` is zero-based. In this example the Windows PC uses slots `0-4`, while the Mac Mini uses slots `5-7`. Both PCs must start from the same base partial/listing file. Each PC can auto-merge its own worker outputs locally; after that, merge the updated partials from the two PCs with `src.merge_outputs`.

Memory sizing for parallel profiles:

- Each active Brave profile usually uses about 700-900 MB of RAM on Windows.
- Each Python worker is small by comparison, usually below 100 MB.
- Keep at least 2 GB free for Windows and other applications.
- Conservative estimate: `max_profiles = floor((free_ram_gb - 2) / 0.9)`.
- Start with 2-3 profiles, check RAM and block rate, then increase one profile at a time.

Print the parallel plan without launching browsers:

```bash
python -m src.main --cdp-parallel-proxies --proxy-list proxy_list.txt --parallel-workers 3 --parallel-dry-run
```

Merge older worker outputs manually:

```bash
python -m src.merge_outputs output/tripadvisor_milan_restaurants_normalized_partial.json output/runs/cdp_parallel/run_YYYYMMDD_HHMMSS/worker_*/tripadvisor_milan_restaurants_normalized_partial.json --output output/tripadvisor_milan_restaurants_normalized_partial.json
```

Compare the new normalized dataset against a legacy Tripadvisor output without modifying either file:

```bash
python -m src.quality_compare --new output/tripadvisor_milan_restaurants_normalized_partial.json --legacy "..\feature-quality-metrics-simone\data\raw\tripadvisor\tripadvisor_scraper_results.json" --output output/tripadvisor_quality_compare_report.json
```

The comparison report counts meaningful non-empty fields, ignores placeholder values such as `NaN`, checks duplicate URL/source IDs, and shows which dataset has better coverage for each field.

Useful options:

```text
--max-pages N                    Stop after N listing pages.
--max-restaurants N              Enrich at most N restaurants.
--delay-seconds N                Delay between listing pages.
--detail-delay-seconds N         Delay between detail pages.
--detail-delay-min-seconds N     Minimum random delay between detail pages.
--detail-delay-max-seconds N     Maximum random delay between detail pages.
--human-detail-scroll            Lightly scroll detail pages before extraction.
--max-reviews-per-restaurant N   Maximum review objects to keep per restaurant.
--partial-every-pages N          Save partial progress every N listing pages.
--partial-every-restaurants N    Save partial progress every N enriched restaurants.
--browser-channel NAME           Use chrome, msedge, or chromium.
--browser-executable-path PATH   Use an explicit browser executable, for example Brave.
--brave-automation-profile       Use Brave with a headed persistent profile.
--browser-warmup-url URL         Open this URL before scraping to warm a persistent profile.
--connect-over-cdp-url URL       Connect to an already-open Chromium/Brave debugging endpoint.
--cdp-detail-from-browser        Enrich missing details through the connected browser tab.
--cdp-parallel-proxies           Launch Brave proxy profiles and parallel CDP workers.
--parallel-workers N             Number of parallel Brave proxy profiles/workers.
--parallel-base-port N           First local CDP port for parallel profiles.
--parallel-profile-root PATH     Root directory for parallel Brave profile folders.
--parallel-output-root PATH      Base directory; each run creates a fresh run_* child.
--parallel-prepare-only          Launch profiles and print commands without starting workers.
--parallel-dry-run               Print the parallel plan without launching browsers or workers.
--parallel-no-manual-wait        Start workers immediately after CDP ports are ready.
--parallel-no-auto-merge         Leave worker partials separate after parallel workers finish.
--parallel-build-listing-if-missing
                                 Build listing-only partial before parallel detail if missing.
--distributed-slot-count N       Total global slots shared across multiple PCs.
--distributed-slot-start N       Zero-based first global slot handled by this PC.
--headed                         Open a visible browser window.
--user-data-dir PATH             Reuse a persistent browser profile.
--manual-unlock                  Wait for manual DataDome or captcha unlock.
--unlock-timeout-seconds N       Wait up to N seconds for manual unlock.
--save-session-only              Save the browser session without scraping JSON output.
--resume                         Continue from the existing partial JSON.
--auto-detail-until-complete     Retry missing detail pages with cooldowns until complete.
--detail-batch-size N            Reopen the browser after N missing detail pages.
--detail-shard-count N           Split missing detail pages across N parallel runs.
--detail-shard-index N           One-based shard number for this run.
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
output/tripadvisor_milan_restaurants_enriched.json
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
