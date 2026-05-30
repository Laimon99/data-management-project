# tests/

Unit and integration tests, mirroring the `services/` structure. Run with `uv run pytest`.

## Structure

```
tests/
├── google_places_api_extract/     # Tests for Stage 1 seed acquisition
│   ├── conftest.py                    # shared fixtures (mock API responses, temp paths)
│   ├── test_config.py                 # env-var loading and validation
│   ├── test_mode_list.py              # Nearby Search pagination, dedup, JSONL output
│   ├── test_mode_detail.py            # Place Details fetching, partial-response handling
│   ├── test_multi_centre.py           # multi-tile city coverage logic
│   ├── test_places_client.py          # HTTP client: retries, backoff on 429/503
│   ├── test_storage.py                # upsert behaviour, checkpoint read/write
│   └── test_tiling.py                 # lat/lon grid generation for city tiling
└── tripadvisor_scraper_extract/   # Tests for Stage 2 Tripadvisor scraper
    └── test_scraper.py                # scraper parsing, checkpoint, output shape
```

## Conventions

- **No real network calls.** All external API and browser interactions are mocked.
- **No real filesystem writes.** Use `tmp_path` (pytest fixture) for any file I/O.
- **Mirror service structure.** A new service under `services/<name>/` gets a matching `tests/<name>/` directory.
- Tests should be fast — avoid sleeping, spawning subprocesses, or loading large fixtures.
