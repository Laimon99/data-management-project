# specs/

Templates and conventions for writing feature specs before implementation begins.

## Contents

| File | Purpose |
|---|---|
| `template.md` | Canonical spec template — copy this when creating a new spec |

## Contents

| File | Purpose |
|---|---|
| `template.md` | Canonical spec template — the `/spec` skill uses this automatically |
| `*.md` (others) | Completed feature specs, one per feature/pipeline stage |

Each spec covers: summary, functional requirements, edge cases, acceptance criteria, open questions, and testing guidelines.

## How to create a new spec

Run `/spec <short description>` — the skill reads `template.md`, generates a filled-out spec in this directory, and switches to a new feature branch automatically.
