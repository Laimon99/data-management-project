# Developer Guide

## Setup

### 1. Install uv

[`uv`](https://github.com/astral-sh/uv) is the package manager this project uses. It also
manages the Python interpreter, so you don't need to install Python separately.

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal after installing so `uv` is on your `PATH`.

### 2. Install dependencies

```bash
uv sync --extra dev
```

This installs everything the project needs — runtime dependencies and dev tools (pytest,
ruff, pre-commit). The `--extra dev` part includes tools that are only needed for
development, not to run the project in production.

`uv` creates a `.venv` folder automatically. You don't need to activate it — just prefix
any command with `uv run` and it runs inside the right environment.

### 3. Register the git hooks

```bash
uv run pre-commit install
```

Run this once after cloning. It sets up automatic formatting checks on every `git commit`
(more on this below). You don't need to run it again on future pulls.

### 4. Add your Google Places API key

Create a `.env` file in the project root. You can do this in your text editor — just
create a file called `.env` with this single line:

```
DATAMAN_GOOGLE_PLACES_API_KEY=your_key_here
```

Replace `your_key_here` with the actual key. The key must have **Places API (New)**
enabled in Google Cloud (*APIs & Services → Library → "Places API (New)" → Enable*).
The Tripadvisor scraper doesn't need an API key.

---

After setup you're ready — see the root [README](../README.md) for how to run each pipeline.

---

## Tools

### uv

`uv` pins exact package versions in a lock file (`uv.lock`) so that everyone on the team
gets the exact same environment — no "works on my machine" surprises. When someone adds
or updates a dependency and pushes the updated lock file, the rest of the team just runs
`uv sync` again to get in sync.

```bash
uv sync --extra dev      # install / update all dependencies
uv run <command>         # run any command inside the project's virtual environment
```

### pre-commit + ruff

[`pre-commit`](https://pre-commit.com/) runs checks automatically every time you
`git commit`. This project uses it to run [`ruff`](https://docs.astral.sh/ruff/), a
Python linter and formatter.

You don't need to install ruff separately — it's included in the dev dependencies and
installed by `uv sync --extra dev`.

**What happens on commit:**
- ruff checks your code for style issues and import ordering
- if it finds something fixable, it fixes the files in place and the commit is aborted
- you then re-stage the fixed files (`git add`) and commit again — it should pass the second time
- if ruff finds something it can't fix automatically, it prints the error and you need to fix it manually before committing

To run the checks manually across all files without committing:

```bash
uv run pre-commit run --all-files
```

### pytest

[`pytest`](https://docs.pytest.org/) is the test runner. Tests live under `tests/` and
mirror the service folder structure. Run it through `uv run` so it uses the project's
environment:

```bash
uv run pytest            # run all tests
uv run pytest -x         # stop on first failure (useful when fixing a chain of errors)
uv run pytest -k name    # run only tests whose name matches a pattern
```

---

## Docker & the storage layer

> **New to Docker? This section is for you.** You only need Docker to run the
> project's databases — the Python code and scrapers still run on your machine with
> `uv run` as before.

### What Docker gives us here

The project's databases — **MongoDB** (where raw data is stored) and **ClickHouse**
(a fast analytics engine, added later) — run inside Docker. That way they behave
identically on macOS, Windows, and Linux, and nobody has to install a database by
hand. `uv` already keeps the *Python* environment reproducible; Docker does the same
job for the *databases*.

### Prerequisite

- **macOS / Windows:** install **Docker Desktop** and start it (the whale icon must
  be running).
- **Linux:** install **Docker Engine** + the Compose plugin from your package manager.

Check it works:

```bash
docker compose version
```

### The mental model (five words)

- **Image** — a frozen template for a program (e.g. "MongoDB 7"). Downloaded once.
- **Container** — a running copy of an image. Start it, stop it, throw it away.
- **Volume** — a named disk that lives *outside* the container, so your data
  survives even when the container is deleted.
- **Service** — one entry in `docker-compose.yml` (we have `mongo` and `clickhouse`).
- **Profile** — an on/off label on a service. Services without a profile start
  always; profiled ones start only when you ask for them.

### Core commands

Run these from the project root (where `docker-compose.yml` lives):

```bash
docker compose up -d        # start the databases in the background
docker compose ps           # see what's running and whether it's healthy
docker compose logs -f      # follow the logs (Ctrl-C to stop watching)
docker compose down         # stop and remove the containers (KEEPS your data)
```

### ⚠️ Data safety: `down` vs `down -v`

- `docker compose down` removes the **containers** but **keeps the named volumes** —
  your data is safe and comes back on the next `up`.
- `docker compose down -v` **also deletes the volumes** — **your data is gone.**

Only use `-v` when you deliberately want a clean slate.

### Profiles: Mongo only, or Mongo + ClickHouse

```bash
docker compose up -d                       # MongoDB only (the default)
docker compose --profile analytics up -d   # MongoDB AND ClickHouse
```

ClickHouse sits behind the `analytics` profile, so a plain `up` won't start it until
we actually need it.

### Connection cheat-sheet

| You are…                         | Use this host  |
|----------------------------------|----------------|
| a tool on your machine (host)    | `localhost:27017` (Mongo), `localhost:8123` (ClickHouse) |
| another container on the network | `mongo` / `clickhouse` (the service names) |

### Cross-platform notes & gotchas

- **Containers are always Linux inside**, even on macOS/Windows — paths in
  `docker-compose.yml` use POSIX `/`.
- **Database data uses named volumes** (`mongo_data`, `clickhouse_data`), not folders
  in the repo, so it never gets committed by accident.
- **Port already in use?** If something else already listens on `27017` (e.g. a Mongo
  you installed locally), set `MONGO_PORT=27018` in your `.env` and run `up` again.
  The same applies to `CLICKHOUSE_HTTP_PORT` / `CLICKHOUSE_NATIVE_PORT`.
- **Line endings** are normalised to LF by `.gitattributes`, so shipped files work the
  same on Windows.

### Where the data loading (ETL) runs

The databases always live in Docker, but the code that *loads* data into them runs on
your **host** with `uv run`. The Mongo load layer is implemented as `services/load/mongo`
(`uv run dataman-load …`) — see
[`../services/load/mongo/README.md`](../services/load/mongo/README.md). The
`mongo → clickhouse` load is implemented as `services/load/clickhouse`
(`uv run dataman-load-clickhouse …`) — see
[`../services/load/clickhouse/README.md`](../services/load/clickhouse/README.md); its
design notes live in [`etl-design.md`](etl-design.md).

