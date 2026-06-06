# TheFork Milan Scraper

Python scraper for TheFork Milan restaurants. It first collects restaurants from listing pages, deduplicates restaurant URLs, then optionally opens each restaurant detail page to enrich the normalized records.

## What It Collects

Listing pages provide fallback data:

- restaurant URL
- restaurant name
- address
- rating
- review count
- cuisine type
- average price
- visible discount
- photo count when visible
- review snippets when visible
- source page number

Detail pages try to improve:

- full restaurant name and address
- latitude and longitude when explicitly present
- rating and review count
- cuisine type and price range
- discount and photo count
- website, phone number, and email when exposed
- social links separately from official website links
- opening hours as both display text and structured data when exposed
- review snippets and configurable reviews per restaurant
- `detail_scraped`

Extraction priority is JSON-LD, embedded JSON, visible HTML text, links and attributes, listing fallback data, then `null`.

## Installation

```bash
cd thefork_scraper
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
python -m src.main --max-pages 1 --max-restaurants 10 --output-dir output/detail_sample
```

Run listing-only mode:

```bash
python -m src.main --no-detail-pages
```

Run the full recommended workflow from scratch:

```bash
python -m src.main --no-detail-pages --log-level INFO
python -m src.main \
  --graphql-cdp-parallel-proxies \
  --proxy-list proxy_list_decodo_runtime.txt \
  --parallel-workers 5 \
  --parallel-base-port 9350 \
  --detail-delay-min-seconds 8 \
  --detail-delay-max-seconds 20 \
  --partial-every-restaurants 5 \
  --max-consecutive-detail-failures 3 \
  --log-level INFO
```

The first command recreates the restaurant listing and writes
`output/thefork_milan_restaurants_normalized_partial.json`. The second command
uses that partial, splits only records with `detail_scraped=false` across
parallel Brave proxy profiles, then automatically merges worker outputs back
into the same partial.

There is currently no single command that first recreates the listing and then
starts parallel GraphQL/CDP detail workers. `--graphql-cdp-parallel-proxies`
expects the partial JSON to already exist. If you want a fresh run, back up or
remove the existing partial first, run listing-only mode, then run the parallel
detail command.

Resume detail scraping from the partial JSON after a block or interruption:

```bash
python -m src.main --resume-detail --detail-delay-seconds 8 --max-consecutive-detail-failures 5
```

Run automatic detail retries until every restaurant is complete:

```bash
python -m src.main --auto-detail-until-complete --detail-delay-seconds 10 --detail-batch-size 24 --max-consecutive-detail-failures 5
```

Recommended conservative no-proxy anti-bot profile for continuing only missing detail pages:

```bash
python -m src.main ^
  --resume-detail ^
  --auto-detail-until-complete ^
  --headed ^
  --pause-on-antibot ^
  --human-detail-scroll ^
  --user-data-dir output/browser_profile_direct ^
  --micro-pause-min-ms 1200 ^
  --micro-pause-max-ms 2500 ^
  --detail-delay-min-seconds 120 ^
  --detail-delay-max-seconds 240 ^
  --detail-batch-size 6 ^
  --max-consecutive-detail-failures 2 ^
  --cooldown-seconds 3600 ^
  --max-cooldown-seconds 14400 ^
  --cooldown-multiplier 2 ^
  --save-final-incomplete ^
  --log-level INFO
```

This profile uses the existing `output/thefork_milan_restaurants_normalized_partial.json`,
skips records where `detail_scraped=true`, and enriches only records where
`detail_scraped=false`. It keeps the browser visible so a captcha or anti-bot
page can be solved manually; after solving it, press Enter in the terminal to
retry the same restaurant. Do not add proxy options unless a proxy run is
explicitly needed.

Recommended Brave automation profile:

```bash
python -m src.main ^
  --resume-detail ^
  --auto-detail-until-complete ^
  --brave-automation-profile ^
  --pause-on-antibot ^
  --human-detail-scroll ^
  --micro-pause-min-ms 1200 ^
  --micro-pause-max-ms 2500 ^
  --detail-delay-min-seconds 120 ^
  --detail-delay-max-seconds 240 ^
  --detail-batch-size 6 ^
  --max-consecutive-detail-failures 2 ^
  --cooldown-seconds 3600 ^
  --max-cooldown-seconds 14400 ^
  --cooldown-multiplier 2 ^
  --save-final-incomplete ^
  --log-level INFO
```

This preset uses the installed Brave executable and opens the browser visibly.
On Windows it defaults to `C:\tmp\thefork_brave_automation_profile` to avoid
long OneDrive/project paths breaking Chromium profile storage. On macOS/Linux it
defaults to `output/brave_automation_profile`. It also warms up the profile on
the configured TheFork listing URL before detail scraping. Before a long run,
open Brave with this profile, browse TheFork normally for a few minutes, accept
cookies if asked, and leave the profile reusable for the scraper.

Recommended CDP GraphQL detail enrichment:

```powershell
Start-Process "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe" -ArgumentList @('--remote-debugging-port=9222')
```

In that Brave window, open TheFork manually, accept cookies or captcha if asked,
and open any TheFork restaurant or Milan listing page. Then run:

```bash
python -m src.main \
  --graphql-detail-from-cdp \
  --connect-over-cdp-url http://127.0.0.1:9222 \
  --max-consecutive-detail-failures 3 \
  --partial-every-restaurants 10 \
  --detail-delay-min-seconds 8 \
  --detail-delay-max-seconds 20 \
  --log-level INFO
```

This mode does not navigate restaurant detail pages with Playwright. It reuses
the already-open manual Brave tab only to execute TheFork GraphQL requests for
records where `detail_scraped=false`, then saves progress to the partial JSON.
Use `--max-restaurants N` for a small test batch, or omit it to continue all
missing records. For separate output, add `--input-partial
output/thefork_milan_restaurants_normalized_partial.json --output-dir
output/runs/graphql_cdp`.

Launch multiple Brave proxy profiles and run GraphQL/CDP workers in parallel:

```bash
python -m src.main \
  --graphql-cdp-parallel-proxies \
  --proxy-list proxy_list_decodo_runtime.txt \
  --parallel-workers 2 \
  --parallel-base-port 9330 \
  --detail-delay-min-seconds 8 \
  --detail-delay-max-seconds 20 \
  --partial-every-restaurants 10 \
  --max-consecutive-detail-failures 3 \
  --log-level INFO
```

This command launches one Brave profile per worker, one proxy per profile, and
one CDP port per profile. Authenticated proxies are handled by a generated local
Chrome extension inside each profile directory. The script pauses before
starting the workers: in every Brave window, open/check TheFork manually and
solve any cookie, captcha, or proxy prompt, then press Enter in the terminal.
Each execution creates a fresh run directory such as
`output/runs/graphql_cdp_parallel/run_YYYYMMDD_HHMMSS/`, and each worker writes
under that directory. This prevents a new run from reusing stale worker partials
from a previous run. When all workers finish, the launcher automatically backs
up the input partial and merges the fresh worker partials back into
`output/thefork_milan_restaurants_normalized_partial.json`.
If the merged dataset has no remaining missing details, it also writes the
shareable final dataset to `output/thefork_milan_restaurants_enriched.json`.
The merge audit is written next to the partial as
`thefork_milan_restaurants_normalized_partial.parallel_merge_report.json`. Add
`--parallel-no-auto-merge` only if you want to inspect and merge worker outputs
manually.

Distributed runs across multiple PCs use the same pending-first split, but with
a global slot count. For example, if this Windows PC runs 5 profiles and a Mac
Mini runs 3 profiles, use 8 total slots:

Windows PC:

```bash
python -m src.main \
  --graphql-cdp-parallel-proxies \
  --proxy-list proxy_list_decodo_runtime.txt \
  --parallel-workers 5 \
  --distributed-slot-count 8 \
  --distributed-slot-start 0 \
  --parallel-base-port 9330 \
  --detail-delay-min-seconds 8 \
  --detail-delay-max-seconds 20 \
  --partial-every-restaurants 10 \
  --max-consecutive-detail-failures 3 \
  --log-level INFO
```

Mac Mini:

```bash
python -m src.main \
  --graphql-cdp-parallel-proxies \
  --proxy-list proxy_list_decodo_runtime.txt \
  --parallel-workers 3 \
  --distributed-slot-count 8 \
  --distributed-slot-start 5 \
  --parallel-base-port 9330 \
  --detail-delay-min-seconds 8 \
  --detail-delay-max-seconds 20 \
  --partial-every-restaurants 10 \
  --max-consecutive-detail-failures 3 \
  --log-level INFO
```

`--distributed-slot-start` is zero-based. In this example the Windows PC uses
slots `0-4`, while the Mac Mini uses slots `5-7`. Both PCs must start from the
same base partial/listing file. Each PC can auto-merge its own worker outputs
locally; after that, merge the updated partials from the two PCs with
`src.merge_outputs`.

Memory sizing for parallel profiles:

- Each active Brave profile usually uses about 700-900 MB of RAM on Windows.
- Each Python worker is small by comparison, usually below 100 MB.
- Keep at least 25-30% of system RAM free so Brave, the OS, and the network stack
  do not start swapping.
- Conservative estimate:
  `max_profiles = floor((free_ram_gb - 2) / 0.9)`.

Examples:

- 8 GB RAM: usually 1-2 profiles.
- 16 GB RAM: usually 3-5 profiles, depending on what else is open.
- 32 GB RAM: more profiles are possible, but 5-8 is already aggressive for
  anti-bot behavior.

In practice, start with 2 profiles, check RAM and block rate, then increase by
one profile at a time. More profiles reduce time only if there are enough
pending records in the corresponding shards and the proxy pool is stable.

Use a dry run before opening browsers:

```bash
python -m src.main --graphql-cdp-parallel-proxies --proxy-list proxy_list_decodo_runtime.txt --parallel-workers 2 --parallel-dry-run
```

If automatic merge was disabled, or if you need to merge an older run manually:

```bash
python -m src.merge_outputs \
  output/thefork_milan_restaurants_normalized_partial.json \
  output/runs/graphql_cdp_parallel/run_YYYYMMDD_HHMMSS/worker_*/thefork_milan_restaurants_normalized_partial.json \
  --output output/thefork_milan_restaurants_normalized_partial.json
```

Run a direct-IP calibration before buying or assigning proxies:

```bash
python -m src.main --calibrate-detail-blocks --calibration-max-records 10 --calibration-delay-seconds 5,10,20
```

Run the same calibration with a proxy list:

```bash
python -m src.main --calibrate-detail-blocks --proxy-list proxy_list.txt --calibration-max-records 10 --calibration-delay-seconds 5,10,20
```

Run the final scraper through one proxy or a rotating proxy list:

```bash
python -m src.main --auto-detail-until-complete --proxy-list proxy_list.txt --detail-delay-seconds 10 --detail-batch-size 24
```

Recommended proxy strategy for postponing IP blocks:

```bash
python -m src.main --proxy-round-robin --proxy-list proxy_list.txt --user-data-dir output/browser_profile --restaurants-per-proxy-turn 1 --proxy-min-rest-seconds 900 --proxy-403-cooldown-seconds 10800 --pool-403-threshold 3 --pool-403-window-seconds 900 --pool-403-cooldown-seconds 21600 --max-url-failures-before-deferral 1 --deferred-url-retry-cycles 300 --detail-delay-min-seconds 60 --detail-delay-max-seconds 180 --proxy-turn-jitter-seconds 30 --human-detail-scroll
```

This mode rotates after a small number of detail pages, gives each proxy a rest window before reuse, applies a long cooldown after HTTP 403 or detected block pages, keeps one persistent browser profile per proxy, saves proxy state after every turn, and stops the run if several distinct proxies receive HTTP 403 within a short window.

Optional Brave run:

```bash
python -m src.main --proxy-round-robin --proxy-list proxy_list.txt --user-data-dir output/browser_profile --browser-executable-path "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --headed --restaurants-per-proxy-turn 1 --proxy-min-rest-seconds 900 --proxy-403-cooldown-seconds 10800 --pool-403-threshold 3 --pool-403-window-seconds 900 --pool-403-cooldown-seconds 21600 --max-url-failures-before-deferral 1 --deferred-url-retry-cycles 300 --detail-delay-min-seconds 60 --detail-delay-max-seconds 180 --proxy-turn-jitter-seconds 30 --human-detail-scroll
```

Manual-assisted anti-block run:

```bash
python -m src.main --resume-detail --auto-detail-until-complete --headed --pause-on-antibot --human-detail-scroll --micro-pause-min-ms 800 --micro-pause-max-ms 1600 --detail-delay-min-seconds 60 --detail-delay-max-seconds 180
```

With `--pause-on-antibot`, the scraper stops when it detects HTTP 403/429 or
captcha/anti-bot page markers. Solve the browser page manually, then press
Enter in the terminal to retry the same restaurant. Records already enriched
with `detail_scraped=true` are skipped automatically.

Run detail enrichment across multiple teammates' PCs without proxies:

```bash
python -m src.main --resume-detail --auto-detail-until-complete --input-partial output/thefork_milan_restaurants_normalized_partial.json --detail-shard-count 3 --detail-shard-index 1 --output-dir output/runs/alice
python -m src.main --resume-detail --auto-detail-until-complete --input-partial output/thefork_milan_restaurants_normalized_partial.json --detail-shard-count 3 --detail-shard-index 2 --output-dir output/runs/bob
python -m src.main --resume-detail --auto-detail-until-complete --input-partial output/thefork_milan_restaurants_normalized_partial.json --detail-shard-count 3 --detail-shard-index 3 --output-dir output/runs/carol
```

Each teammate must use the same starting JSON and a different
`--detail-shard-index`. Each run writes its own partial/final/validation files
under its own `--output-dir`.

Merge teammate outputs after the runs:

```bash
python -m src.merge_outputs ^
  output/runs/alice/thefork_milan_restaurants_normalized_partial.json ^
  output/runs/bob/thefork_milan_restaurants_normalized_partial.json ^
  output/runs/carol/thefork_milan_restaurants_normalized_partial.json ^
  --output output/thefork_milan_restaurants_normalized_partial.json
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
--max-reviews-per-restaurant N   Maximum review objects to keep per restaurant.
--pause-on-antibot               Pause for manual intervention on HTTP 403/429 or anti-bot markers.
--micro-pause-min-ms N           Minimum human-like micro-pause before detail extraction.
--micro-pause-max-ms N           Maximum human-like micro-pause before detail extraction.
--partial-every-pages N          Save partial progress every N listing pages.
--partial-every-restaurants N    Save partial progress every N enriched restaurants.
--browser-channel NAME           Use chrome, msedge, or chromium.
--browser-executable-path PATH   Use an explicit browser executable, for example Brave.
--brave-automation-profile       Use Brave with output/brave_automation_profile and headed mode.
--browser-warmup-url URL         Open this URL before detail scraping to warm a persistent profile.
--connect-over-cdp-url URL       Connect to an already-open Chromium/Brave debugging endpoint.
--graphql-detail-from-cdp        Enrich missing details through in-page TheFork GraphQL requests.
--graphql-review-size N          Reviews requested per restaurant in GraphQL/CDP mode; defaults to --max-reviews-per-restaurant.
--graphql-cdp-parallel-proxies   Launch Brave proxy profiles and parallel GraphQL/CDP workers.
--parallel-workers N             Number of parallel Brave proxy profiles/workers.
--parallel-base-port N           First local CDP port for parallel profiles.
--parallel-profile-root PATH     Root directory for parallel Brave profile folders.
--parallel-output-root PATH      Base directory; each run creates a fresh run_* child.
--parallel-prepare-only          Launch profiles and print commands without starting workers.
--parallel-dry-run               Print the parallel plan without launching browsers or workers.
--parallel-no-manual-wait        Start workers immediately after CDP ports are ready.
--parallel-no-auto-merge         Leave worker partials separate after parallel workers finish.
--distributed-slot-count N       Total global slots shared across multiple PCs.
--distributed-slot-start N       Zero-based first global slot handled by this PC.
--browser-warmup-seconds N       Seconds to wait on the warm-up URL before detail scraping.
--proxy-list PATH                Read one proxy URL per line and rotate it by browser batch.
--proxy-server URL               Use one proxy server, for example http://host:port.
--proxy-username TEXT            Username for --proxy-server.
--proxy-password TEXT            Password for --proxy-server.
--proxy-round-robin              Rotate proxies after a small number of detail pages.
--restaurants-per-proxy-turn N   Detail pages attempted before switching proxy.
--proxy-min-rest-seconds N       Minimum rest time before the same proxy is reused.
--proxy-403-cooldown-seconds N   Cooldown after a detail page returns HTTP 403.
--pool-403-threshold N           Stop after this many distinct proxies return HTTP 403.
--pool-403-window-seconds N      Time window used for the pool-wide HTTP 403 threshold.
--pool-403-cooldown-seconds N    Global cooldown stored after the pool reaches the threshold.
--stop-on-pool-block / --no-stop-on-pool-block
                                 Stop the current run when the pool-wide HTTP 403 threshold is reached.
--proxy-max-failed-turns N       Retire a proxy after repeated failed turns.
--proxy-turn-jitter-seconds N    Add random delay between proxy turns.
--include-direct-ip-after-proxies
                                 Use the direct IP after all proxies are retired.
--calibrate-detail-blocks        Run block-limit calibration and save reports.
--calibration-output-dir PATH    Save calibration reports and sample records.
--calibration-max-records N      Test at most N missing detail records per calibration run.
--calibration-delay-seconds CSV  Test comma-separated delays, for example 5,10,20.
--calibration-batch-size N       Max records attempted in one calibration session.
--calibration-time-budget-hours N
                                 Target scraping time used for proxy estimates.
--calibration-max-proxies N      Max proxies considered by calibration estimates.
--headed                         Open a visible browser window.
--output-dir PATH                Save output files in a custom directory.
--input-partial PATH             Load an existing partial JSON as the starting point.
--no-detail-pages                Skip detail pages.
--resume-detail                  Continue detail enrichment from the partial JSON.
--auto-detail-until-complete     Retry missing detail pages with cooldowns until complete.
--detail-batch-size N            Reopen the browser after N missing detail pages.
--detail-shard-count N           Split missing detail pages across N parallel or teammate runs.
--detail-shard-index N           One-based shard number for this run.
--cooldown-seconds N             Initial cooldown after a blocked detail batch.
--max-cooldown-seconds N         Maximum cooldown after repeated blocked batches.
--cooldown-multiplier N          Multiplier for repeated blocked cooldowns.
--max-auto-detail-cycles N       Maximum automatic retry cycles.
--save-final-incomplete          Write final JSON even if some detail pages are missing.
--max-consecutive-detail-failures N
                                 Stop detail scraping after repeated detail failures.
--log-level LEVEL                Use INFO, DEBUG, WARNING, or ERROR.
```

## Output

Final/shareable enriched JSON:

```text
output/thefork_milan_restaurants_enriched.json
```

Working/resume JSON:

```text
output/thefork_milan_restaurants_normalized_partial.json
```

The `partial` file is the scraper checkpoint and can contain records still
waiting for detail enrichment. The `enriched` file is the clean dataset name to
share after all detail records are complete. It can also be written manually
with `--save-final-incomplete`; in that case, check rows with
`detail_scraped=false` before treating it as complete.

Validation report:

```text
output/thefork_milan_validation_report.json
```

Calibration report:

```text
output/calibration/thefork_block_calibration_report.json
```

Proxy progress report:

```text
output/thefork_proxy_progress_report.json
```

Proxy cooldown state:

```text
output/thefork_proxy_state.json
```

## Notes

- Restaurant links are identified with `a[href*="/ristorante/"]` and filtered to URLs matching `/ristorante/<slug>-r<id>`.
- The restaurant URL, stripped of query and fragment parts, is the main deduplication key.
- If a detail page fails, listing data is kept and `detail_scraped` is set to `false`.
- If repeated detail pages return errors such as HTTP 403, the scraper stops early, keeps the partial JSON, and can be resumed later with `--resume-detail`.
- In `--auto-detail-until-complete` mode, repeated HTTP 403 responses trigger a cooldown and automatic retry from the next missing detail.
- In `--proxy-round-robin` mode, `--max-restaurants` limits only the work queue and does not truncate the partial JSON.
- If every proxy returns HTTP 403 immediately, the pool is already blocked or too low quality; let it cool down or replace it before a full run.
- In `--proxy-round-robin` mode, HTTP 403 events are persisted in `output/thefork_proxy_state.json`; if the pool threshold is reached, the next run stops before making requests until the stored global cooldown expires.
- Current calibration with the direct IP completed 24 of 25 detail pages at 10 seconds delay; the first HTTP 403 appeared on attempt 25. The default detail batch is therefore 24.
- With a 20 hour budget and 15 minute cooldowns, the report estimates 1 proxy as the mathematical minimum and 2 proxies as the recommended margin target.
- Proxy credentials should stay in a local `proxy_list.txt` or environment-specific file; those files are ignored by Git.
- Calibration outputs are kept in `output/calibration/` so the experiments can be reviewed later.
- The fixed normalized city value is `Milan`.
- TheFork card and detail text may remain in Italian because it is source data.
