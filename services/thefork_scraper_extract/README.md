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
uv run thefork-merge-outputs run_a.json run_b.json --output data/raw/thefork/thefork_milan_restaurants_normalized.json
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
--proxy-max-failed-turns N       Retire a proxy after N failed round-robin turns.
--proxy-turn-jitter-seconds N    Random delay added between round-robin turns.
--include-direct-ip-after-proxies
                                 Continue with the direct IP after all proxies retire.
--calibrate-detail-blocks        Run detail-block calibration without changing the partial JSON.
--calibration-output-dir PATH    Where calibration reports are saved.
--log-level LEVEL                Use INFO, DEBUG, WARNING, or ERROR.
```

## Output

Files are written to `data/raw/thefork/` by default (override with `--output-dir`).

Final JSON:

```text
data/raw/thefork/thefork_milan_restaurants_normalized.json
```

Partial progress JSON:

```text
data/raw/thefork/thefork_milan_restaurants_normalized_partial.json
```

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
- The fixed normalized city value is `Milan`.
- TheFork card and detail text may remain in Italian because it is source data.
