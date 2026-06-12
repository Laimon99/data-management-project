from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .constants import REPORT_TABLES_DIRNAME

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd


def _project_root() -> Path:
    """Locate the repo root by walking up from the working directory.

    This module is installed as a *copied snapshot* in ``.venv`` (the source
    path differs from the import path), so a ``__file__``-relative root would
    point inside the virtualenv. We instead search upward from the current
    working directory for the project marker (``pyproject.toml``), falling back
    to the cwd.
    """
    for candidate in (Path.cwd(), *Path.cwd().parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return Path.cwd()


def tables_dir(root: Path | None = None) -> Path:
    """Resolve (and create) the export directory under the project root."""
    base = (root or _project_root()) / REPORT_TABLES_DIRNAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def to_csv(df: "pd.DataFrame", name: str, *, root: Path | None = None) -> Path:
    """Write a DataFrame to ``report/final/tables/<name>.csv`` and return the path."""
    path = tables_dir(root) / f"{name}.csv"
    df.to_csv(path, index=False)
    return path


_LATEX_SPECIALS = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}


def _escape(value: object) -> str:
    return "".join(_LATEX_SPECIALS.get(ch, ch) for ch in str(value))


def to_latex(
    df: "pd.DataFrame",
    name: str,
    *,
    caption: str,
    label: str,
    root: Path | None = None,
) -> Path:
    """Write a booktabs LaTeX table to ``report/final/tables/<name>.tex``.

    Matches the ``report/pre_integration/tables/*.tex`` style (booktabs rules,
    ``\\tiny``), wrapped in a captioned ``table`` float for the final report.
    Numeric columns are right-aligned, others left-aligned. Renders an empty
    result set gracefully as a single explanatory row.
    """
    import pandas as pd

    path = tables_dir(root) / f"{name}.tex"
    columns = list(df.columns)
    col_fmt = (
        "".join("r" if pd.api.types.is_numeric_dtype(df[col]) else "l" for col in columns) or "l"
    )

    header = " & ".join(_escape(col) for col in columns)
    if df.empty:
        body_rows = [f"\\multicolumn{{{max(len(columns), 1)}}}{{c}}{{(no rows)}}"]
    else:
        body_rows = [
            " & ".join(_escape(cell) for cell in row)
            for row in df.itertuples(index=False, name=None)
        ]

    lines = [
        r"\begin{table}[ht]",
        r"\centering",
        f"\\caption{{{_escape(caption)}}}",
        f"\\label{{{label}}}",
        r"{\tiny",
        f"\\begin{{tabular}}{{{col_fmt}}}",
        r"\toprule",
        f"{header} \\\\",
        r"\midrule",
        *[f"{row} \\\\" for row in body_rows],
        r"\bottomrule",
        r"\end{tabular}",
        r"}",
        r"\end{table}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
