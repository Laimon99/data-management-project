This file provides guidance to AI agents when working with code in this repository.

## Project

Data Management project. The goal is to compare restaurant ratings across **Google Maps**, **Tripadvisor**, and **TheFork** for the Milan area — analyzing consistency, quality, and discrepancies.

This repository has a runnable **Google Places seed-acquisition pipeline** and a
runnable **Tripadvisor scraper extract**. TheFork collection, entity resolution,
unified dataset creation, and quality assessment are still in the
planning/scaffolding phase. Refer to `docs/` for the current design intent.

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
```

`target-version = "py311"`.
 Pre-commit should run `ruff --fix` + `ruff-format`.

---

## Pipeline architecture

Five sequential stages — each should live in its own module/directory:

1. **Seed acquisition** — implemented in `services/google_places_api_extract`. Collect a base list of Milan restaurants (name, address, city, lat, lon) from Google Maps / Places API. This is the geographic backbone; coordinates are not re-geocoded later. LLMs may be used to filter out misclassified or noisy venues (e.g. places incorrectly tagged as restaurants).

2. **Per-platform data collection** — Tripadvisor extraction is implemented in `services/tripadvisor_scraper_extract`. For TheFork and later refinements, collect ratings and review counts independently. Each platform gets its own raw output/table.

3. **Entity resolution** — link platform records back to the seed via record linkage. Blocking by proximity + name/address similarity before any expensive matching step. Output: match, no match, uncertain. Measure false matches, missed matches, and ambiguous matches.

4. **Unified dataset** — single table joining all platform ratings per restaurant, with geographic coordinates. Must support at least two queries (e.g. rating difference > 1 star, avg rating by area).

5. **Quality assessment** — evaluate completeness, consistency, uniqueness, timeliness. Show before/after metrics for at least: duplicate removal, name normalization, address standardization, low-review filtering.

---

## Storage

Current acquisition persistence is raw file output under `data/raw/`:
Google Places writes to `data/raw/google_places/` (`restaurants_seed.jsonl` plus checkpoints), and Tripadvisor writes runtime files under `data/raw/tripadvisor/` (`tripadvisor_list_restaurant.txt`, `tripadvisor_scraper_results.json`, `tripadvisor_checkpoint.json`, and browser profile data). Treat DBMS/storage code for downstream stages as out of scope until the storage design is revisited.

A document-based database remains a candidate for later raw platform data, and relational/columnar storage remains acceptable for the integrated ratings table and mandatory queries.

---

## Optional extensions

- Extract structured features from review text using LLMs (sentiment, topics, etc.).

---

## Key constraints

- All `rm` commands are blocked by a pre-tool hook (`.claude/hooks/block_dangerous_commands.sh`).
- Never read `.env`, `secrets/`, `*credential*`, `*.pem`, `*.key` — denied in agent settings.
- Code must be cleanly separated by pipeline stage/source — no new monolithic scripts.
