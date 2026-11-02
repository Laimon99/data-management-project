# Report sources

This directory contains the editable LaTeX sources for the project's three reports.
Compiled, review-ready PDFs live in [`deliverables/`](../deliverables/); generated
analysis exports live in [`artifacts/`](../artifacts/).

## Layout

| Path | Purpose |
|---|---|
| `overleaf/` | Source of the consolidated final report |
| `pre_integration/` | Source and generated tables for the pre-integration quality report |
| `post_integration/` | Source and generated tables for the post-integration assessment |

The `tables/` directories are generated inputs consumed by the corresponding LaTeX
sources. Do not edit them by hand; rerun the relevant assessment service.

## Build the reports

From the repository root, rebuild the pre-integration report on Windows with:

```powershell
powershell -ExecutionPolicy Bypass -File .\report\pre_integration\build_report.ps1
```

The script regenerates its tables, compiles LaTeX twice, and copies the final PDF to
`deliverables/assessments/pre-integration-quality-report.pdf`.

The final report source is self-contained under `report/overleaf/`. Compile
`main.tex` twice from that directory, then copy the resulting PDF to
`deliverables/reports/data-management-project-report.pdf` before publishing an update.

Generated LaTeX auxiliaries and SyncTeX files are ignored by Git.
