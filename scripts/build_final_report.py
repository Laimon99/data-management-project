"""Build the combined final report HTML from the per-question notebooks.

The research analysis lives in twelve self-contained notebooks
(``notebooks/q00``–``notebooks/q11``). This script merges their *already
executed* cells, in order, into a single in-memory notebook and exports it to
``report/final/research_questions_analysis.html`` with code input hidden — a
clean narrative-plus-charts report, matching how the original monolith export
was produced.

Run after re-executing the notebooks:

    uv run python scripts/build_final_report.py
"""

from __future__ import annotations

from pathlib import Path

import nbformat
from nbconvert import HTMLExporter

REPO = Path(__file__).resolve().parent.parent
NOTEBOOK_DIR = REPO / "notebooks"
OUTPUT = REPO / "report" / "final" / "research_questions_analysis.html"
TITLE = "research_questions_analysis"

# Explicit order: overview first, then Q1–Q11.
NOTEBOOKS = [
    "q00_overview.ipynb",
    "q01_consistency.ipynb",
    "q02_disagreement.ipynb",
    "q03_quality_link.ipynb",
    "q04_sparse_data.ipynb",
    "q05_platform_bias.ipynb",
    "q06_popularity.ipynb",
    "q07_location_completeness.ipynb",
    "q08_cuisine.ipynb",
    "q09_price.ipynb",
    "q10_selection_effect.ipynb",
    "q11_photos.ipynb",
]


def merge_notebooks() -> nbformat.NotebookNode:
    """Concatenate the per-question notebooks into one notebook node."""
    merged: nbformat.NotebookNode | None = None
    for name in NOTEBOOKS:
        path = NOTEBOOK_DIR / name
        if not path.exists():
            raise FileNotFoundError(f"missing notebook: {path}")
        nb = nbformat.read(path, as_version=4)
        if merged is None:
            merged = nb
        else:
            merged.cells.extend(nb.cells)
    assert merged is not None, "no notebooks merged"
    return merged


def main() -> None:
    merged = merge_notebooks()

    exporter = HTMLExporter()
    exporter.exclude_input = True  # report shows narrative + outputs only
    exporter.embed_images = True

    body, _ = exporter.from_notebook_node(merged)
    body = body.replace("<title>Notebook</title>", f"<title>{TITLE}</title>", 1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(body, encoding="utf-8")
    n_code = sum(1 for c in merged.cells if c.cell_type == "code")
    print(
        f"wrote {OUTPUT.relative_to(REPO)} "
        f"({len(merged.cells)} cells, {n_code} code) "
        f"from {len(NOTEBOOKS)} notebooks"
    )


if __name__ == "__main__":
    main()
