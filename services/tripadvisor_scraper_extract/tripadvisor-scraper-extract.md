# Tripadvisor Scraper Extract

The Tripadvisor extractor is packaged in `services/tripadvisor_scraper_extract` and
is runnable through `uv`.

## Run

```bash
uv run tripadvisor-scraper-extract --order bottom
```

Use `--order bottom` when another teammate is scraping from the top of the URL
list. The default is `--order top`.

## Browser compatibility

The scraper auto-detects Brave on macOS, Windows, and Linux. If Brave is
installed in a non-standard location, pass it explicitly:

```bash
uv run tripadvisor-scraper-extract --order bottom --brave-path "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
```

If Brave is unavailable, the scraper falls back to Playwright-managed Chromium.
That browser may need to be installed once:

```bash
uv run playwright install chromium
```

## Runtime files

Runtime data is kept out of `src` and written under `data/raw/tripadvisor/` by
default:

| File | Purpose |
|---|---|
| `tripadvisor_list_restaurant.txt` | Source URL list. A bundled copy is copied here on first run if absent. |
| `tripadvisor_scraper_results.json` | Accumulated extracted restaurant records. |
| `tripadvisor_checkpoint.json` | Resume state with processed and failed URLs. |
| `brave_automation_profile/` | Persistent browser profile for the scraper session. |

Override the runtime directory or URL file when needed:

```bash
uv run tripadvisor-scraper-extract --data-dir data/raw/tripadvisor_run_2
uv run tripadvisor-scraper-extract --url-file path/to/custom_urls.txt
```
