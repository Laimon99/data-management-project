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
- opening hours
- review snippets and up to 5 reviews
- `detail_scraped`

Extraction priority is JSON-LD, embedded JSON, visible HTML text, links and attributes, listing fallback data, then `null`.

## Installation

```bash
uv sync
uv run playwright install chromium
```

The scraper first tries the installed Chrome browser channel, then Microsoft Edge, then bundled Chromium.

## Execution

Run the full listing + detail scraper:

```bash
uv run thefork-scraper-extract
```

Run a small validation sample without overwriting the main output directory:

```bash
uv run thefork-scraper-extract --max-pages 1 --max-restaurants 10 --output-dir data/raw/thefork/detail_sample
```

Run listing-only mode:

```bash
uv run thefork-scraper-extract --no-detail-pages
```

Resume detail scraping from the partial JSON after a block or interruption:

```bash
uv run thefork-scraper-extract --resume-detail --detail-delay-seconds 8 --max-consecutive-detail-failures 5
```

Run automatic detail retries until every restaurant is complete:

```bash
uv run thefork-scraper-extract --auto-detail-until-complete --detail-delay-seconds 10 --detail-batch-size 25 --max-consecutive-detail-failures 5
```

### Proxy rotation (anti-block)

When TheFork returns repeated HTTP 403 on detail pages, route detail scraping
through proxies. Provide proxies via a list file (one `http://host:port` or
`http://user:pass@host:port` per line) or a single server, then pick a rotation
strategy:

```bash
# Burn through each proxy until it stops producing detail records, then rotate.
uv run thefork-scraper-extract --resume-detail --proxy-list proxies.txt --proxy-burn-through

# Rotate proxies every few detail pages and rest each one before reuse.
uv run thefork-scraper-extract --resume-detail --proxy-list proxies.txt --proxy-round-robin \
    --restaurants-per-proxy-turn 3 --proxy-min-rest-seconds 90
```

> Proxy list files (`proxy_list*.txt`, `proxies.txt`, `*.proxy`) may embed
> credentials and are gitignored — never commit them.

### Calibration

Measure detail-page blocking limits and estimate how many proxies are needed,
without touching the main partial JSON:

```bash
uv run thefork-scraper-extract --calibrate-detail-blocks --proxy-list proxies.txt \
    --calibration-delay-seconds 5,10,20 --calibration-max-records 10
```

Reports and sample records are written under `data/raw/thefork/calibration/`.

### Merging outputs

Merge several output JSON files (for example shards from teammate runs),
preferring completed detail records:

```bash
uv run thefork-merge-outputs run_a.json run_b.json --output data/raw/thefork/thefork_milan_restaurants_enriched.json
```

### Brave automation profile

For long anti-block runs, use a headed Brave profile that is warmed up on
TheFork before detail scraping:

```bash
uv run thefork-scraper-extract --resume-detail --auto-detail-until-complete \
    --brave-automation-profile --pause-on-antibot --human-detail-scroll \
    --detail-delay-min-seconds 120 --detail-delay-max-seconds 240 \
    --detail-batch-size 6 --save-final-incomplete
```

This preset uses the installed Brave executable and opens the browser visibly.
On Windows it defaults to `C:\tmp\thefork_brave_automation_profile`; on
macOS/Linux it defaults to `data/raw/thefork/brave_automation_profile`. Before a
long run, open Brave with this profile, browse TheFork for a few minutes, accept
cookies, and leave it reusable for the scraper.

### GraphQL detail enrichment over CDP

When Playwright detail navigation is blocked, enrich missing records through
TheFork's GraphQL API executed inside an already-open Brave/Chromium tab. Start
the browser with a remote debugging port, open TheFork manually (solve
cookies/captcha), then run:

```bash
uv run thefork-scraper-extract --graphql-detail-from-cdp \
    --connect-over-cdp-url http://127.0.0.1:9222 \
    --partial-every-restaurants 10 \
    --detail-delay-min-seconds 8 --detail-delay-max-seconds 20
```

This mode never navigates detail pages; it reuses the open tab only to run
GraphQL requests for records where `detail_scraped=false`, then saves progress
to the partial JSON. Use `--graphql-review-size N` to cap reviews per restaurant.

### Parallel proxy workers

Launch one Brave proxy profile per worker and run GraphQL/CDP enrichment in
parallel:

```bash
uv run thefork-scraper-extract --graphql-cdp-parallel-proxies \
    --proxy-list proxies.txt --parallel-workers 2 --parallel-base-port 9330 \
    --partial-every-restaurants 10
```

Each execution creates a fresh run directory under
`data/raw/thefork/runs/graphql_cdp_parallel/run_YYYYMMDD_HHMMSS/`. The launcher
pauses so you can check TheFork in each Brave window, then press Enter to start
the workers. When they finish, it backs up the input partial, merges the fresh
worker partials back into it, and — if no records still miss detail data —
writes the shareable `thefork_milan_restaurants_enriched.json`. Preview the plan
first with `--parallel-dry-run`; disable the automatic merge with
`--parallel-no-auto-merge`. Each active Brave profile uses roughly 700–900 MB of
RAM, so start with 2 profiles, watch RAM and the block rate, then add one at a
time.

### Distributed runs across multiple PCs

Distributed runs use the same pending-first split, but with a global slot count.
For example, if one machine runs 5 profiles and a second machine runs 3, use 8
total slots. The first machine takes slots `0-4`, the second takes slots `5-7`.

First machine (5 workers, slots 0–4):

```bash
uv run thefork-scraper-extract --graphql-cdp-parallel-proxies \
    --proxy-list proxies.txt --parallel-workers 5 \
    --distributed-slot-count 8 --distributed-slot-start 0 \
    --parallel-base-port 9330 --partial-every-restaurants 10
```

Second machine (3 workers, slots 5–7):

```bash
uv run thefork-scraper-extract --graphql-cdp-parallel-proxies \
    --proxy-list proxies.txt --parallel-workers 3 \
    --distributed-slot-count 8 --distributed-slot-start 5 \
    --parallel-base-port 9330 --partial-every-restaurants 10
```

`--distributed-slot-start` is zero-based. Both machines must start from the same
base partial/listing file. Each machine can auto-merge its own worker outputs
locally; afterward, merge the updated partials from the two machines with
`uv run thefork-merge-outputs`.

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
--output-dir PATH                Save output files in a custom directory.
--no-detail-pages                Skip detail pages.
--resume-detail                  Continue detail enrichment from the partial JSON.
--auto-detail-until-complete     Retry missing detail pages with cooldowns until complete.
--detail-batch-size N            Reopen the browser after N missing detail pages.
--cooldown-seconds N             Initial cooldown after a blocked detail batch.
--max-cooldown-seconds N         Maximum cooldown after repeated blocked batches.
--cooldown-multiplier N          Multiplier for repeated blocked cooldowns.
--max-auto-detail-cycles N       Maximum automatic retry cycles.
--save-final-incomplete          Write final JSON even if some detail pages are missing.
--max-consecutive-detail-failures N
                                 Stop detail scraping after repeated detail failures.
--input-partial PATH             Seed a separate run from an existing partial JSON.
--user-data-dir PATH             Persistent browser profile directory.
--proxy-list PATH                Text file with one proxy URL per line.
--proxy-server URL               Single proxy server, e.g. http://host:port.
--proxy-username NAME            Username for --proxy-server.
--proxy-password PASS            Password for --proxy-server.
--proxy-burn-through             Use each proxy until it stops producing records, then rotate.
--proxy-round-robin              Rotate proxies every few detail pages and rest each one.
--restaurants-per-proxy-turn N   Detail pages per proxy before rotating (round-robin).
--proxy-min-rest-seconds N       Minimum rest before reusing a proxy (round-robin).
--proxy-403-cooldown-seconds N   Cooldown for a proxy after an HTTP 403 (round-robin).
--pool-403-threshold N           Stop after this many distinct proxies return HTTP 403.
--pool-403-window-seconds N      Time window for the pool-wide HTTP 403 threshold.
--pool-403-cooldown-seconds N    Global cooldown stored after the pool hits the threshold.
--stop-on-pool-block / --no-stop-on-pool-block
                                 Stop the run when the pool-wide HTTP 403 threshold is reached.
--max-url-failures-before-deferral N
                                 Skip a detail URL after this many failed attempts.
--deferred-url-retry-cycles N    Round-robin cycles before retrying a deferred URL.
--proxy-max-failed-turns N       Retire a proxy after N failed round-robin turns.
--proxy-turn-jitter-seconds N    Random delay added between round-robin turns.
--include-direct-ip-after-proxies
                                 Continue with the direct IP after all proxies retire.
--brave-automation-profile       Use a headed Brave profile warmed up on TheFork.
--browser-executable-path PATH   Use an explicit browser executable, e.g. Brave.
--browser-warmup-url URL         Open this URL before detail scraping to warm a profile.
--browser-warmup-seconds N       Seconds to wait on the warm-up URL.
--connect-over-cdp-url URL       Connect to an already-open Chromium/Brave debug endpoint.
--graphql-detail-from-cdp        Enrich missing details via in-page TheFork GraphQL requests.
--graphql-review-size N          Reviews requested per restaurant in GraphQL/CDP mode.
--graphql-cdp-parallel-proxies   Launch Brave proxy profiles and parallel GraphQL/CDP workers.
--parallel-workers N             Number of parallel Brave proxy profiles/workers.
--parallel-base-port N           First local CDP port for parallel profiles.
--parallel-profile-root PATH     Root directory for parallel Brave profile folders.
--parallel-output-root PATH      Base directory; each run creates a fresh run_* child.
--parallel-prepare-only          Launch profiles and print commands without starting workers.
--parallel-dry-run               Print the parallel plan without launching browsers.
--parallel-no-manual-wait        Start workers immediately after CDP ports are ready.
--parallel-no-auto-merge         Leave worker partials separate after parallel workers finish.
--distributed-slot-count N       Total global slots shared across multiple PCs.
--distributed-slot-start N       Zero-based first global slot handled by this PC.
--detail-shard-count N           Split missing detail pages across N parallel/teammate runs.
--detail-shard-index N           One-based shard number for this run.
--calibrate-detail-blocks        Run detail-block calibration without changing the partial JSON.
--calibration-output-dir PATH    Where calibration reports are saved.
--log-level LEVEL                Use INFO, DEBUG, WARNING, or ERROR.
```

## Output

Files are written to `data/raw/thefork/` by default (override with `--output-dir`).

Final / shareable enriched JSON (written when all detail records are complete):

```text
data/raw/thefork/thefork_milan_restaurants_enriched.json
```

Working / resume partial JSON (the scraper checkpoint; may still contain records
waiting for detail enrichment):

```text
data/raw/thefork/thefork_milan_restaurants_normalized_partial.json
```

The `partial` file is the checkpoint and can be resumed with `--resume-detail`.
The `enriched` file is the clean dataset to share once every record has
`detail_scraped=true`; with `--save-final-incomplete` it may be written early, so
check for `detail_scraped=false` rows before treating it as complete.

Validation report:

```text
data/raw/thefork/thefork_milan_validation_report.json
```

Runtime artifacts from proxy/calibration runs (all gitignored, not tracked):

```text
data/raw/thefork/thefork_proxy_state.json
data/raw/thefork/thefork_proxy_progress_report.json
data/raw/thefork/calibration/
data/raw/thefork/runs/
data/raw/thefork/browser_profile/        # single persistent profile
data/raw/thefork/browser_profiles/       # per-proxy profiles
```

## Notes

- Restaurant links are identified with `a[href*="/ristorante/"]` and filtered to URLs matching `/ristorante/<slug>-r<id>`.
- The restaurant URL, stripped of query and fragment parts, is the main deduplication key.
- If a detail page fails, listing data is kept and `detail_scraped` is set to `false`.
- If repeated detail pages return errors such as HTTP 403, the scraper stops early, keeps the partial JSON, and can be resumed later with `--resume-detail`.
- In `--auto-detail-until-complete` mode, repeated HTTP 403 responses trigger a cooldown and automatic retry from the next missing detail.
- In `--proxy-round-robin` mode, HTTP 403 events are persisted in `data/raw/thefork/thefork_proxy_state.json`; if the pool threshold is reached, the next run stops before making requests until the stored global cooldown expires.
- `--graphql-detail-from-cdp` and `--graphql-cdp-parallel-proxies` reuse an already-open Brave/Chromium tab over CDP and never navigate detail pages with Playwright.
- The fixed normalized city value is `Milan`.
- TheFork card and detail text may remain in Italian because it is source data.
