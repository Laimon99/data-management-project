from __future__ import annotations

from pathlib import Path

import typer

from .profiler import run_assessment
from .reporting import write_latex_tables, write_markdown_report

app = typer.Typer(help="Compute data quality metrics for the restaurant datasets.")


@app.command()
def profile(
    google_path: Path = typer.Option(
        Path("data/raw/google_places/restaurants_seed.jsonl"),
        help="Google Places JSONL seed dataset.",
    ),
    tripadvisor_path: Path = typer.Option(
        Path("data/raw/tripadvisor/tripadvisor_scraper_results.json"),
        help="Tripadvisor raw JSON dataset.",
    ),
    thefork_path: Path = typer.Option(
        Path("data/raw/thefork/thefork_milan_restaurants_enriched.json"),
        help="TheFork final enriched JSON dataset.",
    ),
    output_dir: Path = typer.Option(
        Path("data/quality"),
        help="Directory where JSON/CSV quality outputs are written.",
    ),
    markdown_report: Path = typer.Option(
        Path("docs/data-quality-assessment.md"),
        help="Generated Markdown report section.",
    ),
    latex_tables_dir: Path = typer.Option(
        Path("report/tables"),
        help="Directory where generated LaTeX tables are written.",
    ),
    low_review_threshold: int = typer.Option(
        20,
        help="Review-count threshold below which ratings are treated as sparse evidence.",
    ),
) -> None:
    """Profile source datasets and generate report-ready artifacts."""
    payload = run_assessment(
        google_path=google_path,
        tripadvisor_path=tripadvisor_path,
        thefork_path=thefork_path,
        output_dir=output_dir,
        low_review_threshold=low_review_threshold,
    )
    write_markdown_report(payload, markdown_report)
    write_latex_tables(payload, latex_tables_dir)

    typer.echo("Quality assessment completed.")
    typer.echo(f"Metrics: {output_dir / 'source_quality_metrics.json'}")
    typer.echo(f"Field coverage: {output_dir / 'field_coverage.csv'}")
    typer.echo(f"Anomalies: {output_dir / 'anomalies.csv'}")
    typer.echo(f"Markdown report: {markdown_report}")
    typer.echo(f"LaTeX tables: {latex_tables_dir}")
