"""Export the whole ClickHouse analysis tables to CSV/Parquet.

**Every research question reads from the single flat ``restaurants_integrated``
table** — Q1, Q2, Q4, Q5, Q7, Q8 and Q10 are all just views/aggregations over it,
so that one table is the complete underlying dataset for them. The three
per-platform ``restaurants_clean_*`` tables round out the pre-integration picture
(``all`` dumps every table).

Read-only: it only issues ``SELECT * FROM <table>``. Parquet needs ``pyarrow``;
CSV is the default and always works.

Examples
--------
    uv run dataman-analysis-export                       # -> restaurants_integrated.csv
    uv run dataman-analysis-export all --format parquet  # every table, parquet
    uv run dataman-analysis-export all --out data/analysis_export
"""

from __future__ import annotations

from pathlib import Path

import typer

from .config import AnalysisSettings, clickhouse_client

app = typer.Typer(add_completion=False, no_args_is_help=False)

# The four flat tables the ClickHouse load layer materialises (see
# load.clickhouse.targets). restaurants_integrated is the one every question
# reads from; the clean_* tables are the pre-integration per-platform inputs.
ALL_TABLES = [
    "restaurants_integrated",
    "restaurants_clean_google",
    "restaurants_clean_tripadvisor",
    "restaurants_clean_thefork",
]

DEFAULT_OUT = "data/analysis_export"


@app.command()
def main(
    which: list[str] = typer.Argument(
        None,
        help=(
            "Table(s) to dump, or 'all'. Default: restaurants_integrated (the table "
            "every question reads from). Choices: " + ", ".join(ALL_TABLES) + ", all."
        ),
    ),
    fmt: str = typer.Option("csv", "--format", help="csv or parquet.", case_sensitive=False),
    out: str = typer.Option(DEFAULT_OUT, "--out", help="Output directory."),
) -> None:
    """Dump whole ClickHouse table(s) as CSV/Parquet."""
    fmt = fmt.lower()
    if fmt not in {"csv", "parquet"}:
        raise typer.BadParameter("--format must be 'csv' or 'parquet'.")

    selected = ALL_TABLES if (which and "all" in which) else (which or ["restaurants_integrated"])
    unknown = [t for t in selected if t not in ALL_TABLES]
    if unknown:
        raise typer.BadParameter(
            f"Unknown table(s): {', '.join(unknown)}. Use 'all' or one of {', '.join(ALL_TABLES)}."
        )

    client = clickhouse_client(AnalysisSettings())
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    typer.echo(f"Exporting {len(selected)} table(s) -> {out_dir}/ ({fmt})")

    for table in selected:
        df = client.query_df(f"SELECT * FROM {table}")
        path = out_dir / f"{table}.{fmt}"
        if fmt == "parquet":
            try:
                df.to_parquet(path, index=False)
            except ImportError as exc:  # pragma: no cover - env-dependent
                raise typer.BadParameter(
                    "Parquet export needs 'pyarrow' (not installed). Use --format csv "
                    "or run `uv add pyarrow`."
                ) from exc
        else:
            df.to_csv(path, index=False)
        typer.echo(f"  {path}  ({len(df):,} rows x {len(df.columns)} cols)")


if __name__ == "__main__":  # pragma: no cover
    app()
