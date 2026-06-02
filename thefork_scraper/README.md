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

Resume detail scraping from the partial JSON after a block or interruption:

```bash
python -m src.main --resume-detail --detail-delay-seconds 8 --max-consecutive-detail-failures 5
```

Run automatic detail retries until every restaurant is complete:

```bash
python -m src.main --auto-detail-until-complete --detail-delay-seconds 10 --detail-batch-size 24 --max-consecutive-detail-failures 5
```

Run detail enrichment across multiple teammates' PCs without proxies:

```bash
python -m src.main --resume-detail --auto-detail-until-complete --input-partial output/thefork_milan_restaurants_normalized.json --detail-shard-count 3 --detail-shard-index 1 --output-dir output/runs/alice
python -m src.main --resume-detail --auto-detail-until-complete --input-partial output/thefork_milan_restaurants_normalized.json --detail-shard-count 3 --detail-shard-index 2 --output-dir output/runs/bob
python -m src.main --resume-detail --auto-detail-until-complete --input-partial output/thefork_milan_restaurants_normalized.json --detail-shard-count 3 --detail-shard-index 3 --output-dir output/runs/carol
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
  --output output/thefork_milan_restaurants_normalized.json
```

Run a small direct-IP calibration to estimate detail-page blocking:

```bash
python -m src.main --calibrate-detail-blocks --calibration-max-records 10 --calibration-delay-seconds 5,10,20
```

Optional headed Brave run without proxies:

```bash
python -m src.main --resume-detail --auto-detail-until-complete --input-partial output/thefork_milan_restaurants_normalized.json --output-dir output/runs/alice --browser-executable-path "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --headed
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
--calibrate-detail-blocks        Run block-limit calibration and save reports.
--calibration-output-dir PATH    Save calibration reports and sample records.
--calibration-max-records N      Test at most N missing detail records per calibration run.
--calibration-delay-seconds CSV  Test comma-separated delays, for example 5,10,20.
--calibration-batch-size N       Max records attempted in one calibration session.
--headed                         Open a visible browser window.
--output-dir PATH                Save output files in a custom directory.
--input-partial PATH             Load an existing partial JSON as the starting point.
--no-detail-pages                Skip detail pages.
--resume-detail                  Continue detail enrichment from the partial JSON.
--auto-detail-until-complete     Retry missing detail pages with cooldowns until complete.
--detail-batch-size N            Reopen the browser after N missing detail pages.
--detail-shard-count N           Split missing detail pages across N teammate runs.
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

Final JSON:

```text
output/thefork_milan_restaurants_normalized.json
```

Partial progress JSON:

```text
output/thefork_milan_restaurants_normalized_partial.json
```

Validation report:

```text
output/thefork_milan_validation_report.json
```

Calibration report:

```text
output/calibration/thefork_block_calibration_report.json
```

## Notes

- Restaurant links are identified with `a[href*="/ristorante/"]` and filtered to URLs matching `/ristorante/<slug>-r<id>`.
- The restaurant URL, stripped of query and fragment parts, is the main deduplication key.
- If a detail page fails, listing data is kept and `detail_scraped` is set to `false`.
- If repeated detail pages return errors such as HTTP 403, the scraper stops early, keeps the partial JSON, and can be resumed later with `--resume-detail`.
- In `--auto-detail-until-complete` mode, repeated HTTP 403 responses trigger a cooldown and automatic retry from the next missing detail.
- In distributed no-proxy runs, every teammate should pass the same `--input-partial` and use a different `--detail-shard-index`.
- `python -m src.merge_outputs` deduplicates by normalized restaurant URL and prefers records with completed detail pages.
- Current calibration with the direct IP completed 24 of 25 detail pages at 10 seconds delay; the first HTTP 403 appeared on attempt 25. The default detail batch is therefore 24.
- Proxy options still exist in `python -m src.main --help` for local experiments. The shared team workflow above is designed to run without proxies.
- Proxy credentials should stay in a local `proxy_list.txt` or environment-specific file; those files are ignored by Git.
- Calibration outputs are kept in `output/calibration/` so the experiments can be reviewed later.
- The fixed normalized city value is `Milan`.
- TheFork card and detail text may remain in Italian because it is source data.
