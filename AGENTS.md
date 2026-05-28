This file provides guidance to AI agents when working with code in this repository.

## Project

Data Management project. The goal is to compare restaurant ratings across **Google Maps**, **Tripadvisor**, and **TheFork** for the Milan area — analyzing consistency, quality, and discrepancies.

This repository has a runnable **Stage 1 seed-acquisition pipeline**. Later stages are still in the planning/scaffolding phase. Refer to `docs/` for the current design intent.

---

## Intended tooling

Python stack managed with `uv`. All infrastructure (databases, scrapers at scale) via Docker/docker-compose.

```bash
uv sync                              # install deps from lock file
uv run pre-commit install            # install git hooks (once after clone)
uv run pre-commit run --all-files    # lint/format manually
uv run pytest                        # run tests
```

`pyproject.toml` should use ruff with `line-length = 100`, `target-version = "py311"`, `select = ["E", "F", "I"]`. Pre-commit should run `ruff --fix` + `ruff-format`.

---

## Pipeline architecture

Five sequential stages — each should live in its own module/directory:

1. **Seed acquisition** — collect a base list of Milan restaurants (name, address, city, lat, lon) from Google Maps (via Places API or scraping). This is the geographic backbone; coordinates are not re-geocoded later. LLMs may be used to filter out misclassified or noisy venues (e.g. places incorrectly tagged as restaurants).

2. **Per-platform data collection** — for each restaurant in the seed, collect ratings and review counts from Tripadvisor and TheFork independently. Each platform gets its own table.

3. **Entity resolution** — link platform records back to the seed via record linkage. Blocking by proximity + name/address similarity before any expensive matching step. Output: match, no match, uncertain. Measure false matches, missed matches, and ambiguous matches.

4. **Unified dataset** — single table joining all platform ratings per restaurant, with geographic coordinates. Must support at least two queries (e.g. rating difference > 1 star, avg rating by area).

5. **Quality assessment** — evaluate completeness, consistency, uniqueness, timeliness. Show before/after metrics for at least: duplicate removal, name normalization, address standardization, low-review filtering.

---

## Storage

Current Stage 1 persistence is raw JSONL output under `data/` (`restaurants_seed.jsonl` plus checkpoints). Treat DBMS/storage code for downstream stages as out of scope until the storage design is revisited.

A document-based database remains a candidate for later raw platform data, and relational/columnar storage remains acceptable for the integrated ratings table and mandatory queries.

---

## Optional extensions

- Extract structured features from review text using LLMs (sentiment, topics, etc.).

---

## Key constraints

- All `rm` commands are blocked by a pre-tool hook (`.claude/hooks/block_dangerous_commands.sh`).
- Never read `.env`, `secrets/`, `*credential*`, `*.pem`, `*.key` — denied in `.claude/settings.json`.
- Plans go in `./_plans` (configured in settings).
- Code must be cleanly separated by pipeline stage — no monolithic scripts.
- Auto-memory is disabled (`autoMemoryEnabled: false`).
