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

