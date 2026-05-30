# specs/

Templates and conventions for writing feature specs before implementation begins.

## Contents

| File | Purpose |
|---|---|
| `template.md` | Canonical spec template — copy this when creating a new spec |

## Where completed specs live

Completed feature specs are stored in `_specs/` (prefixed with underscore to keep them separate from the template directory). Each spec file in `_specs/` covers one feature or pipeline stage and includes: summary, functional requirements, edge cases, acceptance criteria, open questions, and testing guidelines.

## How to create a new spec

1. Copy `specs/template.md` to `_specs/<feature-name>.md`.
2. Fill in all sections before writing any code.
3. Reference the spec in the PR description and link to the corresponding test file.
