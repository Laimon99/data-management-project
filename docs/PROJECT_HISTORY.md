# Project history and preservation

The repository originated as the working and submission repository for the University
of Milan-Bicocca Data Management course, academic year 2025/2026. That structure kept
implementation notes, datasets, generated files, agent tooling, reports, and the entire
project narrative together because it optimized for team delivery during the course.

After the final presentation, the repository was reorganized as a public portfolio
project. The cleanup changed presentation and navigation, not authorship or project
history.

## Preserved academic submission

The dated branch
[`backup/academic-submission-2026-08-27`](https://github.com/Laimon99/data-management-project/tree/backup/academic-submission-2026-08-27)
points to commit `8b5635e`, the final `main` snapshot retrieved from GitHub before the
showcase cleanup.

It preserves:

- the complete raw, processed, and analytical data files tracked at submission time;
- original generated artifacts and report layout;
- development-specific AI/agent configuration;
- the long-form project README and completed/historical checklist;
- every source file and Git commit reachable from the academic `main` branch.

To inspect it locally without modifying the showcase branch:

```bash
git fetch origin
git switch --detach origin/backup/academic-submission-2026-08-27
```

Return with `git switch main` (or your current feature branch).

## Showcase changes

The public-facing tree now uses:

- a concise root README with links to detailed documentation;
- `deliverables/` for final PDFs and presentations;
- `report/` and `diagrams/` for editable sources;
- `artifacts/` for generated analysis and diagram output;
- public data samples and aggregate metrics instead of complete datasets;
- GitHub Actions for lint and tests;
- explicit code-license and data-usage terms.

The original root README is preserved verbatim in
[`archive/ACADEMIC_README.md`](archive/ACADEMIC_README.md). Its relative links reflect
its former position at the repository root and are retained for historical fidelity.
