# TheFork Scraper Branch

This branch contains the TheFork scraper used to collect Milan restaurant data.

The scraper lives in [`thefork_scraper/`](thefork_scraper/). See
[`thefork_scraper/README.md`](thefork_scraper/README.md) for installation,
execution, no-proxy multi-PC runs, and merge instructions.

Quick start:

```bash
cd thefork_scraper
pip install -r requirements.txt
python -m playwright install chromium
python -m src.main --no-detail-pages
```

For team detail enrichment without proxies, use the shard commands documented in
`thefork_scraper/README.md`.
