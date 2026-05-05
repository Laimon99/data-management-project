# uv + pre-commit Project Setup

## 1. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 2. Init project

```bash
uv init my-project
cd my-project
git init
```

## 3. Add dependencies

```bash
uv add <package1> <package2>
uv add --dev pre-commit pytest
```

## 4. Configure `pyproject.toml`

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I"]

[tool.pytest.ini_options]
pythonpath = ["."]
```

## 5. Create `.pre-commit-config.yaml`

Python only:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

With JS/CSS/HTML (add below the ruff block):

```yaml
  - repo: https://github.com/pre-commit/mirrors-prettier
    rev: v3.1.0
    hooks:
      - id: prettier
        types_or: [ts, javascript, html, css, json]
```

## 6. Install hooks

```bash
uv run pre-commit install
```

## Commands reference

```bash
uv sync                              # install/update deps from lock file
uv run pre-commit install            # install git hook (run once after clone)
uv run pre-commit run --all-files    # lint/format everything manually
uv run pre-commit autoupdate         # bump hook versions to latest
uv run pytest                        # run tests
```