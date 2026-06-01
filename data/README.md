# data/

Raw pipeline output — files written by acquisition services, never modified by hand.

## Structure

```
data/
└── raw/
    ├── google_places/         # Stage 1: Google Places seed acquisition
    │   ├── restaurants_seed.jsonl      # deduplicated venue records (one JSON doc per line)
    │   └── *.checkpoint.json           # progress state for resumable runs
    ├── tripadvisor/           # Stage 2: Tripadvisor scraper output
    │   ├── tripadvisor_list_restaurant.txt   # raw restaurant URL list
    │   ├── tripadvisor_scraper_results.json  # scraped rating/review records
    │   ├── tripadvisor_checkpoint.json       # scraper resume state
    │   └── browser_profile/                  # Playwright persistent browser profile
    └── thefork/               # Stage 2: TheFork scraper output
        ├── thefork_milan_restaurants_normalized.json          # normalized listing/detail records
        ├── thefork_milan_restaurants_normalized_partial.json  # partial-progress snapshot
        └── thefork_milan_validation_report.json               # field-coverage validation report
```

## Rules

- **Read-only after write.** Services append or upsert; nothing downstream mutates raw files.
- **No manual edits.** Re-run the service to regenerate.
- **Not committed.** The `data/` tree is gitignored; raw output is local only.

## Downstream use

These files are the inputs to Stage 3 (entity resolution) once storage is formalised. The JSONL and JSON formats are chosen so records can be imported into MongoDB or read directly by DuckDB without transformation. See `docs/storage-design.md` for the storage architecture decision.
