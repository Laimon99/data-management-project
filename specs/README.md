# specs/

Templates and conventions for writing feature specs before implementation begins.

## Contents

| File | Purpose |
|---|---|
| `template.md` | Canonical spec template — the `/spec` skill uses this automatically |
| `*.md` (others) | Completed feature specs, one per feature/pipeline stage |

Current specs include: `google-places-seed-acquisition`, `multi-centre-neighbourhood-tiling`,
`multi-browser-chromium-detection`, `tripadvisor-elt-transform` (+ `tripadvisor-elt-transform.plan`),
`thefork-elt-transform`, `google-places-elt-transform`, `clean-transforms-er-prep`,
`tripadvisor-clean-parity`, `entity-resolution`, `data-storage-layer`, `storage-load-layer`,
and `research-questions-analysis`.

Each spec covers: summary, functional requirements, edge cases, acceptance criteria, open questions, and testing guidelines.

## How to create a new spec

Run `/spec <short description>` — the skill reads `template.md`, generates a filled-out spec in this directory, and switches to a new feature branch automatically.
