# Report

LaTeX/PDF deliverables for the project. The folder is organized by reporting stage so
each report has a clear home as the project progresses.

## Layout

```
report/
├── pre_integration/    # Pre-integration quality report (done)
│   ├── main.tex        #   LaTeX source
│   ├── main.pdf        #   compiled PDF
│   ├── build_report.ps1#   Windows build: regenerate tables + compile main.pdf
│   └── tables/         #   auto-generated LaTeX tables (DO NOT edit by hand)
├── post_integration/   # Post-integration quality report (in progress)
└── final/              # Final consolidated project report (planned)
```

## Stages

### Pre-integration report — `pre_integration/` *(done)*

The raw, pre-cleaning quality baseline. Its tables in `pre_integration/tables/` are
**generated**, not hand-written: `services/quality_assessment` (`uv run quality-assessment`)
writes them to `report/pre_integration/tables/` and the Markdown summary to
`docs/data-quality-assessment.md`. `pre_integration/main.tex` pulls each table in via
`\input{tables/...}`.

> The `pre_integration/tables/` directory and the `report/pre_integration/main.tex` /
> `report/pre_integration/main.pdf` paths are referenced directly by
> `services/quality_assessment` (see `cli.py`, `__main__.py`, `reporting.py`) and by
> `pre_integration/build_report.ps1`. **Do not move or rename these** — regenerate them
> instead.

Rebuild from the current raw datasets:

```bash
uv run quality-assessment && cd report/pre_integration && \
  pdflatex -interaction=nonstopmode -halt-on-error main.tex && \
  pdflatex -interaction=nonstopmode -halt-on-error main.tex
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\report\pre_integration\build_report.ps1
```

### Post-integration report — `post_integration/` *(in progress)*

Quality re-assessed **after** cleaning, entity resolution, and unification: completeness,
consistency, uniqueness, and timeliness on `restaurants_integrated`, with before/after
deltas against the pre-integration baseline above. New `.tex` sources and any
stage-specific tables live here.

### Final report — `final/` *(planned)*

The consolidated deliverable that ties together domain/research questions, acquisition,
storage, integration, both quality stages, and the analysis results.
