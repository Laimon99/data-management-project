# ClickHouse Docker networking issue

> **Status: RESOLVED** (see [Resolution](#resolution)). Kept as an operational
> runbook in case the symptom recurs.

## Resolution

Two separate problems were blocking the end-to-end load; both are fixed.

### 1. Stale container pinned to a dead network

The hypothesis below was correct. A stopped `dataman-clickhouse` container from a
previous run still existed (`Exited (128)`), and `docker inspect` showed it pinned to
the old network ID `427e7cc2…`. Every `compose up` tried to reattach that dead container
to a network that no longer existed (the live `data-management-project_default` network
had since been recreated with a new ID) instead of creating a fresh container.

Fix — remove the stale container (volume untouched), then re-up:

```bash
docker container remove --force dataman-clickhouse   # NB: `docker rm` is blocked by the repo hook
docker compose --profile analytics up -d
```

ClickHouse then started healthy. The named volume `clickhouse_data` was never touched, so
no data was lost.

### 2. Loader never created the `dataman` database

Once ClickHouse was up, `uv run dataman-load-clickhouse all` still failed with
`Code: 81 … Database dataman does not exist (UNKNOWN_DATABASE)`. The loader connected with
`database="dataman"` selected and issued `CREATE TABLE IF NOT EXISTS {db}.…`, but nothing
ever created the **database** itself — and selecting a missing DB at connect time raises.
The integration test masked this because its fixture creates the DB.

Fix (in `services/load/clickhouse/loader.py::open_clickhouse`): connect *without* a target
database, run `CREATE DATABASE IF NOT EXISTS {db}`, then select it. The loader owns its
schema (it already creates the tables), so it owns the database too — no docker-compose
init script needed (an init script only runs on a fresh volume anyway). Regression covered
by `test_open_clickhouse_bootstraps_database`.

After both fixes the full load succeeds (29,723 rows across the four tables) and survives a
container restart.

## Context

After implementing `services/load/clickhouse` (branch `feature/ch-load`), we tried to
start ClickHouse via the `analytics` Docker Compose profile to run the end-to-end test.

## What we ran

```bash
docker compose --profile analytics up -d
```

MongoDB starts fine. ClickHouse fails every time with:

```
Container dataman-clickhouse  Starting
Error response from daemon: failed to set up container networking:
  network 427e7cc230884f98aa831f24179066309c597ba3f81c7a195cd61486d1967664 not found
```

The same stale network hash (`427e7cc2…`) appears in the error on every attempt, even
after:

- `docker compose down` + re-up
- Full Docker Desktop quit-and-reopen
- `docker rm dataman-clickhouse` + `docker network prune -f` + re-up

MongoDB (`dataman-mongo`) starts and stays healthy on all attempts. Only the ClickHouse
container (`dataman-clickhouse`) triggers this error.

## Hypothesis

Docker Desktop has a stale internal record of the `dataman-clickhouse` container that
pins it to the old network ID `427e7cc2…`. Every `docker compose up` recreates the
default network with a new ID, but the cached container config still references the old
one, causing the networking step to fail.

## What to try in the new session

1. `docker inspect dataman-clickhouse` — check if a stopped/dead container still exists
   with that network ID baked in.
2. `docker rm -f dataman-clickhouse` — force-remove any lingering container record.
3. `docker network ls` + `docker network prune -f` — remove all unused networks.
4. `docker system prune -f` (no `-v`, keep volumes) — clear all stopped containers,
   dangling images, and unused networks in one shot.
5. After the prune: `docker compose --profile analytics up -d` fresh.
6. If still failing: check Docker Desktop settings → reset to factory defaults
   (last resort — does NOT delete named volumes).

## ClickHouse service definition (for reference)

From `docker-compose.yml`:

```yaml
clickhouse:
  image: clickhouse/clickhouse-server:26.3
  container_name: dataman-clickhouse
  profiles: ["analytics"]
  environment:
    CLICKHOUSE_SKIP_USER_SETUP: "1"
  ports:
    - "${CLICKHOUSE_HTTP_PORT:-8123}:8123"
    - "${CLICKHOUSE_NATIVE_PORT:-9000}:9000"
  volumes:
    - clickhouse_data:/var/lib/clickhouse
  restart: unless-stopped
```

Named volume `clickhouse_data` is separate from the network — it is safe across any
prune that does not use `-v`.
