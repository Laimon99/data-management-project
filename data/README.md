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
        ├── thefork_milan_restaurants_enriched.json            # enriched listing+detail records (canonical load input)
        ├── thefork_milan_restaurants_normalized*.json         # earlier normalized snapshots (full + partial progress)
        └── thefork_milan_*_report.json                        # merge / field-coverage validation reports
```

Later pipeline stages also write generated (non-raw) subdirectories under `data/` —
`processed/`, `quality/` (assessment metrics + hand-labeled gold CSVs),
`analysis_export/`, and `exports/` (e.g. `mongo_json/`). These are outputs of the
transform / assessment / analysis stages, not hand-authored inputs.

## Rules

- **Read-only after write.** Services append or upsert; nothing downstream mutates raw files.
- **No manual edits.** Re-run the service to regenerate.
- **Not committed.** The `data/` tree is gitignored; raw output is local only.

## Downstream use

These raw files are the inputs to the Load layer (`services/load/mongo`, `uv run dataman-load`), which upserts them into MongoDB — the system of record for the transform, entity-resolution, unified-dataset, and analysis stages (with ClickHouse as the analytics layer). See `docs/storage-design.md` for the storage architecture decision.
