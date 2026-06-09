This file provides guidance to AI agents when working with code in this repository.

## Project

Data Management project. The goal is to compare restaurant ratings across **Google Maps**, **Tripadvisor**, and **TheFork** for the Milan area — analyzing consistency, quality, and discrepancies.

This repository has runnable extractors for all three sources — **Google Places**
(seed acquisition), **Tripadvisor**, and **TheFork** — plus a **MongoDB Load layer**
(`services/load/mongo`), transforms for all three platforms
(`services/transform/{google,tripadvisor,thefork}_clean`), **entity resolution**
(`services/transform/entity_resolution`), a **unified dataset** builder
(`services/transform/unified_dataset`), a **quality assessment** service
(`services/quality_assessment`), a **ClickHouse Load layer** (`services/load/clickhouse`)
that loads the cleaned and integrated collections from MongoDB into four flat ClickHouse
analytics tables, and **Docker storage infrastructure** (MongoDB as system of record +
ClickHouse analytics behind the `analytics` profile). The final report/queries are still
pending. Refer to `docs/` for design details.

Services are grouped by pipeline stage: `services/extract/`, `services/load/`,
`services/transform/` (PEP 420 namespace packages → imports like
`extract.google_places_api`, `load.mongo`, `transform.tripadvisor_clean`,
`transform.google_clean`).

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
uv run tripadvisor-clean             # clean + geocode Tripadvisor → restaurants_clean_tripadvisor (transform)
uv run google-clean                  # clean+normalize Google → restaurants_clean_google (transform)
uv run thefork-clean                 # clean+normalize TheFork → restaurants_clean_thefork (transform)
uv run dataman-entity-resolve        # entity resolution across all three platforms
uv run dataman-er-calibrate          # calibrate entity resolution thresholds
uv run dataman-unify                 # build unified dataset → restaurants_unified
uv run quality-assessment            # run quality assessment on integrated data
docker compose --profile analytics up -d clickhouse  # start ClickHouse (analytics layer)
uv run dataman-load-clickhouse all   # load cleaned + integrated collections → ClickHouse
```

`target-version = "py311"`.
 Pre-commit should run `ruff --fix` + `ruff-format`.

> **Editable-install gotcha.** Because each service's source path
> (`services/<stage>/<name>`) differs from its import path (`<stage>.<name>`),
> the project is installed as a *copied snapshot* in `.venv`, not a live link.
> So `uv run <console-script>` (e.g. `uv run tripadvisor-clean`) keeps
> running the **old** code after you edit a service — and a plain `uv sync`
> won't refresh it. After editing service code, before verifying through an
> entrypoint, run `uv sync --reinstall-package data-management-project`.
> Tests are unaffected: `uv run pytest` reads source directly via
> `pythonpath = ["services"]`, so prefer tests for verification.

---

## Pipeline architecture

Five sequential stages — each should live in its own module/directory:

1. **Seed acquisition** — implemented in `services/extract/google_places_api`. Collect a base list of Milan restaurants (name, address, city, lat, lon) from Google Maps / Places API. This is the geographic backbone; coordinates are not re-geocoded later. LLMs may be used to filter out misclassified or noisy venues (e.g. places incorrectly tagged as restaurants).

2. **Per-platform data collection** — Tripadvisor extraction is implemented in `services/extract/tripadvisor_scraper` and TheFork extraction in `services/extract/thefork_scraper`. Each platform collects ratings and review counts independently into its own raw output/table. Raw files are then loaded into MongoDB by the **Load layer** (`services/load/mongo`, `uv run dataman-load`): a pure raw passthrough that idempotently upserts into `restaurants_raw_{google,tripadvisor,thefork}`, keyed on each source's natural id.

3. **Entity resolution** — implemented in `services/transform/entity_resolution` (`uv run dataman-entity-resolve`). Links platform records back to the seed via record linkage: blocking by proximity + name/address similarity, scoring, and calibration (`uv run dataman-er-calibrate`). Output: match, no match, uncertain. Prerequisites: all three platform transforms must run first. Tripadvisor records are enriched with lat/lon by `services/transform/tripadvisor_clean` (`uv run tripadvisor-clean`, Nominatim geocoding). Google seed is cleaned by `services/transform/google_clean` (`uv run google-clean`): projects lean fields, normalizes name/city, flags dining relevance (`is_dining` / `category_tier`). TheFork is cleaned by `services/transform/thefork_clean` (`uv run thefork-clean`).

4. **Unified dataset** — implemented in `services/transform/unified_dataset` (`uv run dataman-unify`). Joins all platform ratings per resolved restaurant into `restaurants_unified`, with geographic coordinates. Supports queries such as rating difference > 1 star or avg rating by area.

5. **Quality assessment** — implemented in `services/quality_assessment` (`uv run quality-assessment`). Evaluates completeness, consistency, uniqueness, timeliness. Pre-integration report is at `report/pre_integration/main.pdf`; post-integration assessment is pending.

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
