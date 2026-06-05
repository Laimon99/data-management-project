This file provides guidance to AI agents when working with code in this repository.

## Project

Data Management project. The goal is to compare restaurant ratings across **Google Maps**, **Tripadvisor**, and **TheFork** for the Milan area — analyzing consistency, quality, and discrepancies.

This repository has runnable extractors for all three sources — **Google Places**
(seed acquisition), **Tripadvisor**, and **TheFork** — plus a runnable **MongoDB
Load layer** (`services/load/mongo`), a **Tripadvisor geocoding enrichment**
(`services/transform/tripadvisor_geocode`), and **Docker storage infrastructure**
(MongoDB as system of record + a ClickHouse analytics scaffold). Entity resolution,
unified dataset creation, and quality assessment are still in the planning/scaffolding
phase. Refer to `docs/` for the current design intent.

Services are grouped by pipeline stage: `services/extract/`, `services/load/`,
`services/transform/` (PEP 420 namespace packages → imports like
`extract.google_places_api`, `load.mongo`, `transform.tripadvisor_geocode`).

---

## Intended tooling

Python stack managed with `uv`. All infrastructure (databases, scrapers at scale) via Docker/docker-compose.

```bash
uv sync                              # install deps from lock file
uv run pre-commit install            # install git hooks (once after clone)
uv run pre-commit run --all-files    # lint/format manually
uv run pytest                        # run tests
uv run google-places-api-extract     # Google Places seed CLI
uv run tripadvisor-scraper-extract   # Tripadvisor Playwright scraper CLI
uv run thefork-scraper-extract       # TheFork Playwright scraper CLI
docker compose up -d mongo           # start MongoDB (storage layer)
uv run dataman-load all              # load raw files into MongoDB (Load layer)
uv run tripadvisor-geocode-enrich    # geocode Tripadvisor addresses → lat/lon (transform)
```

`target-version = "py311"`.
 Pre-commit should run `ruff --fix` + `ruff-format`.

---

## Pipeline architecture

Five sequential stages — each should live in its own module/directory:

1. **Seed acquisition** — implemented in `services/extract/google_places_api`. Collect a base list of Milan restaurants (name, address, city, lat, lon) from Google Maps / Places API. This is the geographic backbone; coordinates are not re-geocoded later. LLMs may be used to filter out misclassified or noisy venues (e.g. places incorrectly tagged as restaurants).

2. **Per-platform data collection** — Tripadvisor extraction is implemented in `services/extract/tripadvisor_scraper` and TheFork extraction in `services/extract/thefork_scraper`. Each platform collects ratings and review counts independently into its own raw output/table. Raw files are then loaded into MongoDB by the **Load layer** (`services/load/mongo`, `uv run dataman-load`): a pure raw passthrough that idempotently upserts into `restaurants_raw_{google,tripadvisor,thefork}`, keyed on each source's natural id.

3. **Entity resolution** — link platform records back to the seed via record linkage. Blocking by proximity + name/address similarity before any expensive matching step. Output: match, no match, uncertain. Measure false matches, missed matches, and ambiguous matches. Tripadvisor records (which lack coordinates) are enriched with lat/lon beforehand by `services/transform/tripadvisor_geocode` (`uv run tripadvisor-geocode-enrich`, Nominatim/OpenStreetMap) to enable proximity blocking.

4. **Unified dataset** — single table joining all platform ratings per restaurant, with geographic coordinates. Must support at least two queries (e.g. rating difference > 1 star, avg rating by area).

5. **Quality assessment** — evaluate completeness, consistency, uniqueness, timeliness. Show before/after metrics for at least: duplicate removal, name normalization, address standardization, low-review filtering.

---

## Storage

Acquisition persistence is raw file output under `data/raw/`: Google Places writes to `data/raw/google_places/` (`restaurants_seed.jsonl` plus checkpoints), Tripadvisor writes runtime files under `data/raw/tripadvisor/` (`tripadvisor_list_restaurant.txt`, `tripadvisor_scraper_results.json`, `tripadvisor_checkpoint.json`, and browser profile data), and TheFork writes to `data/raw/thefork/`.

The storage layer is now implemented as reproducible Docker infrastructure (`docker-compose.yml`): **MongoDB** is the document system of record and is populated from the raw files by `services/load/mongo` (`uv run dataman-load`); **ClickHouse** is scaffolded behind an opt-in `analytics` profile for the future integrated ratings table and mandatory queries. See `docs/storage-design.md` for the DBMS evaluation and `docs/etl-design.md` for the load-layer design.

---

## Optional extensions

- Extract structured features from review text using LLMs (sentiment, topics, etc.).

---

## Key constraints

- All `rm` commands are blocked by a pre-tool hook (`.claude/hooks/block_dangerous_commands.sh`).
- Never read `.env`, `secrets/`, `*credential*`, `*.pem`, `*.key` — denied in agent settings.
- Code must be cleanly separated by pipeline stage/source — no new monolithic scripts.
