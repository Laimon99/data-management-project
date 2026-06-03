# Spec for data-storage-layer
branch: feature/data-storage-layer

> **Note — rescoped during planning.** This branch delivers the storage **infrastructure
> only** (MongoDB + ClickHouse via Docker, env config, docs). The Python loader/ETL, the
> `docker/loader/Dockerfile`, and the `services/storage/` package described below are
> **deferred to a later step** and designed in [`../docs/etl-design.md`](../docs/etl-design.md).
> The Acceptance Criteria below describe the *combined* feature, not this PR alone — see
> `_plans/plan-this-replicated-starfish.md` for the approved scope of this branch.

## Summary

Stand up the project's **data storage layer** as reproducible Docker infrastructure, plus a
beginner-friendly guide for teammates who are new to Docker.

The layer is **MongoDB now, ClickHouse prepared for later**:

- **MongoDB** — document system-of-record for the raw nested seed and (later) per-platform
  records. Runs on every `docker compose up`.
- **ClickHouse** — columnar engine for the integrated ratings table and the mandatory
  analytical queries. Scaffolded now behind an opt-in compose **profile** so it exists and is
  ready, but does not start by default.

Loading data into Mongo is done by a **single Python ETL/loader module with two runtimes**:
the **host path** (`uv run …`, the default everyday path, talks to `localhost`) and an
optional **container path** (built from a Dockerfile, talks to services by name — used for an
all-in-Docker bring-up and future CI). The loader reuses the existing `MongoSeedStore`,
`SeedDoc`, and config in `services/google_places_api_extract/` rather than duplicating Mongo
logic.

**Web scrapers stay on the host** (Playwright + the antibot Chrome profile under
`data/raw/tripadvisor/`); nothing scraping-related is containerized.

This supersedes the current bare single-service `docker-compose.yml` (Mongo only, no health
checks, no ClickHouse, no loader) and builds on the prior design exploration in
`docs/storage-design.md` (which recommended MongoDB + a columnar engine; this spec locks the
columnar pick as **ClickHouse**).

### Context / decisions locked during brainstorming

- **Docker's job = stateful services** (Mongo, ClickHouse) run identically on Mac, Windows,
  and Linux. Python env reproducibility is already handled by **uv** — so the loader is *not*
  containerized for env reasons; the Dockerfile exists for the composed/CI path and as the
  home of the future `mongo → clickhouse` ETL.
- **ClickHouse via compose profile** (`analytics`), off by default.
- **Manual load** (no auto-seed on startup); one documented command.
- **Named volumes** for DB data so data survives `docker compose down` and is removed only by
  the explicit `docker compose down -v`.
- **Cross-platform team:** author on macOS (Apple Silicon), teammates on Windows, professor
  assumed on Linux.

## Functional Requirements

### 1. docker-compose.yml (replaces the existing one)

- **`mongo` service**
  - Official `mongo:7` image; container name stable (e.g. `dataman-mongo`).
  - Port `27017` exposed to the host (configurable, to allow remap on port conflict).
  - Named volume `mongo_data` mounted at `/data/db`.
  - Health check so dependents can wait for readiness.
  - `restart: unless-stopped`.
  - Runs on a plain `docker compose up` (no profile).
- **`clickhouse` service**
  - Official `clickhouse/clickhouse-server` image (arm64-compatible for Apple Silicon).
  - Behind compose profile **`analytics`** — does **not** start on a plain `up`.
  - Ports `8123` (HTTP) and `9000` (native) exposed to the host (configurable).
  - Named volume `clickhouse_data` for persistence; appropriate `ulimits` (nofile) as the
    image expects.
  - Health check.
- **`loader` service**
  - Built from the project Dockerfile (see §2). Behind a profile (e.g. **`tools`**) so it
    does **not** start on a plain `up`; invoked on demand via
    `docker compose run --rm loader …`.
  - `depends_on` Mongo (and, for ClickHouse ETL later, ClickHouse) with health condition.
  - Reads the project's `data/` directory (mounted; read-only is acceptable for raw input).
  - Reaches Mongo by **service name** (`mongodb://mongo:27017`) when run in-container.
- All services share a single compose network so the loader can reach the DBs by name.
- A single top-level `volumes:` block declares `mongo_data` and `clickhouse_data`.

### 2. docker/loader/Dockerfile

- **uv-based** Python image targeting **Python 3.11** (matches `pyproject` / ruff target).
- Installs project dependencies from the lock file (`uv sync`) so the environment matches the
  host.
- **No Playwright browsers** — the `playwright` pip package may install transitively, but the
  image must **not** run `playwright install` / download browser binaries; the loader does no
  scraping.
- Entrypoint runs the storage CLI (§3). Default command may be a help/usage message so a bare
  `run` is harmless.

### 3. Storage / loader Python module

- New package `services/storage/` (own pipeline-stage concern per repo conventions — no
  monolithic script), registered in `pyproject` (`[project.scripts]`,
  `[tool.hatch.build.targets.wheel].packages`, ruff `known-first-party`).
- Exposes a CLI (Typer `app`, consistent with `google_places_api_extract`) with a console
  script, e.g. **`storage-load-seed`**.
- **`load-seed` command:** reads the existing
  `data/raw/google_places/restaurants_seed.jsonl`, validates each line with the existing
  `SeedDoc` schema, and **upserts** into Mongo by reusing the existing `MongoSeedStore`
  (which already creates the unique `place_id` index and handles upsert/merge). It must be
  **idempotent** — re-running does not create duplicates.
- Reads connection settings from environment (reuse the existing `DATAMAN_*` settings:
  `DATAMAN_MONGO_URI`, `DATAMAN_MONGO_DB`, `DATAMAN_MONGO_COLLECTION`). Path to the JSONL is
  configurable with a sensible default.
- Prints a short summary on completion (records read, upserted, skipped/invalid).
- **Two runtimes, same code:**
  - **Host (default):** `uv run storage-load-seed …` with `DATAMAN_MONGO_URI=mongodb://localhost:27017`.
  - **Container (optional):** `docker compose run --rm loader load-seed` with
    `DATAMAN_MONGO_URI=mongodb://mongo:27017`.
- **ClickHouse ETL is scaffolded, not implemented:** leave a clearly-marked placeholder
  (stub command and/or documented TODO) for the future `mongo → clickhouse` ETL so the shape
  exists without building it now (YAGNI).

### 4. Configuration (.env / .env.example)

- Update `.env.example` so a teammate can copy it and run with zero edits for local dev:
  - Mongo connection (`DATAMAN_MONGO_URI`, `DATAMAN_MONGO_DB`, `DATAMAN_MONGO_COLLECTION`).
  - ClickHouse connection placeholders for later (e.g. `DATAMAN_CLICKHOUSE_HOST`,
    `DATAMAN_CLICKHOUSE_PORT`, db name) — present but unused until ETL exists.
  - Any compose-level variables (host port overrides) clearly separated from `DATAMAN_*`
    application settings, since they live in different namespaces.
- **Local dev default = Mongo without authentication** (localhost only) to minimize beginner
  friction; document this is dev-only and how to enable auth later. (See Open Questions.)

### 5. Beginner Docker guide (docs/docker-guide.md)

A short, friendly guide for teammates new to Docker. Must cover:

- **Prerequisite:** Docker Desktop on macOS/Windows; native Docker Engine on Linux.
- **Mental model:** image vs container vs volume vs service vs profile, in plain language.
- **Core commands:** `docker compose up` / `up -d`, `ps`, `logs`, `down`.
- **Data-safety rule (called out prominently):** `down` keeps named volumes (data safe);
  **only `down -v` deletes them** (data lost).
- **Profiles:** `docker compose up` (Mongo only) vs
  `docker compose --profile analytics up` (adds ClickHouse).
- **The two load paths:** host `uv run storage-load-seed` (default) and
  `docker compose run --rm loader load-seed` (optional), and *why* there are two.
- **Where ETL runs:** DBs are always in Docker; the ETL Python process runs on the host by
  default — explicitly clarified, since this caused confusion.
- **Cross-platform notes & gotchas:** containers are always Linux inside; named volumes
  (not bind mounts) for DB data; how to remap a port on conflict; line-ending handling for
  any shipped shell scripts (verify `.gitattributes` covers them).
- **Connection cheat-sheet:** host tools use `localhost:27017` / `localhost:8123`;
  in-container services use `mongo` / `clickhouse` by name.

### 6. Cleanup

- Remove the old bare `docker-compose.yml` content by replacing it with the new definition.
- Ensure named-volume directories / any local data are covered by `.gitignore` as needed
  (DB data must never be committed).

## Possible Edge Cases

- **`docker compose down -v`** wiping a teammate's loaded data — must be loud in the guide.
- **Port already in use** (e.g. a locally-installed Mongo on 27017) — remap must be documented
  and supported via env var.
- **Apple Silicon / arm64** image availability for ClickHouse — pin an image/tag that ships
  arm64 to avoid slow emulation.
- **Re-running `load-seed`** must not duplicate documents (idempotent upsert on `place_id`).
- **Malformed / partial JSONL line** in the seed file — loader should skip and report rather
  than abort the whole import.
- **Missing seed file** (teammate hasn't produced/obtained it) — loader exits with a clear,
  actionable message, not a stack trace.
- **Mongo not ready yet** when the loader runs — host path should fail with a clear hint to
  start compose first; container path should wait via `depends_on` health condition.
- **Windows line endings / paths** breaking shipped scripts — guard via `.gitattributes` and
  POSIX paths in compose.
- **ClickHouse started without enough file descriptors** — set required `ulimits` so it boots
  cleanly.
- **Loader image accidentally pulling browser binaries**, bloating the image — must be
  explicitly avoided.

## Acceptance Criteria

- `docker compose up -d` starts **only Mongo** (healthy); ClickHouse and loader do **not**
  start.
- `docker compose --profile analytics up -d` additionally starts a healthy **ClickHouse**.
- After `docker compose up -d`, running the **host** loader (`uv run storage-load-seed`) with
  the example env imports `restaurants_seed.jsonl` into Mongo; the collection contains one
  document per unique `place_id`.
- Running the **container** loader (`docker compose run --rm loader load-seed`) achieves the
  same result.
- Running `load-seed` **twice** leaves the same document count (idempotent).
- `docker compose down` then `up -d` again: **data is still present** (volume persisted).
- `docker compose down -v` removes the data (verifies the documented behavior).
- The loader image **does not** contain Playwright browser binaries.
- `docs/docker-guide.md` exists and lets a Docker newcomer go from clone → DBs up → data
  loaded using only the documented commands, including the `down` vs `down -v` warning and the
  two load paths.
- `.env.example` works out-of-the-box for local dev with no edits.
- Existing host scrapers (`uv run …`) are unaffected (no scraping moved into Docker).
- `uv run pytest`, `ruff`, and `ruff-format` pass.

## Open Questions

- **Mongo auth:** default to no-auth localhost dev (proposed) vs ship root credentials in `.env` from day one? (Proposed: no-auth for simplicity; document enabling auth.) - yep
- **Loader profile name:** `tools` vs folding the loader into the `analytics` profile.
- **ClickHouse image tag:** pin `latest`-style vs a specific stable version for reproducibility
  (lean: pin a specific arm64-supporting tag). - find in web lts version
- **Mongo schema/init:** create indexes only via the loader (current `MongoSeedStore` behavior)
  vs add a Mongo init step in compose. (Lean: keep index creation in the store/loader.)
- **Where the `services/storage/` package sits** relative to the existing empty
  `services/pipeline/` package — merge or keep separate. - in services

## Out of Scope

- Implementing the actual **`mongo → clickhouse` ETL** and the integrated ratings schema
  (only scaffolded/placeholdered here).
- The **mandatory analytical queries** and quality-assessment logic (later pipeline stages).
- **Entity resolution** and per-platform raw collections in Mongo (TheFork/Tripadvisor
  ingestion into the DB).
- **Containerizing any scraper** or moving Playwright into Docker.
- Production concerns: backups, replication, secrets management, auth hardening, TLS.
- OpenSearch / DuckDB / other engines from the design doc (ClickHouse is the chosen columnar
  engine).

## Feature Testing Guidelines

Create test file(s) under `/tests` (pytest, `mongomock` is already a dev dependency). Keep it
focused — do not over-test infrastructure:

- **load-seed happy path:** given a small in-memory/fixture JSONL of `SeedDoc` records,
  loading into a `mongomock` collection results in the expected document count and `place_id`
  values.
- **Idempotency:** running the load twice yields the same document count (no duplicates).
- **Malformed line handling:** a fixture with one invalid JSON line is skipped and reported,
  and valid lines still load.
- **Missing seed file:** loader raises/exits with a clear, specific error message.
- **Config wiring:** `make_store()` (or the loader's store selection) returns a Mongo-backed
  store when `DATAMAN_MONGO_URI` is set and the backend is `mongo`.
- (Optional, no live containers) A lightweight check that the `docker-compose.yml` parses and
  declares the expected services, profiles, and named volumes.

Do not write tests that require live Docker containers in CI; container/compose behavior is
validated manually per the Acceptance Criteria.
