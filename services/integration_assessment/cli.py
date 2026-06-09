from __future__ import annotations

import csv
from pathlib import Path
from typing import Annotated

import typer

from transform.entity_resolution.calibrate import (
    CALIBRATION_COLUMNS,
    _find_google,
    _find_source,
    _row_for_candidate,
    select_calibration_sample,
)

from .assessment import run_assessment
from .config import IntegrationAssessmentSettings
from .gold import gold_ids, load_gold_rows
from .mongo import open_collections
from .reporting import write_latex_tables, write_markdown_report

app = typer.Typer(
    help="Measure post-integration entity-resolution and geocoding error.",
    invoke_without_command=True,
)


GoldOption = Annotated[
    list[Path] | None,
    typer.Option(
        "--gold-csv",
        help="Out-of-sample hand-labeled gold CSV. May be passed multiple times.",
    ),
]
InCalibrationGoldOption = Annotated[
    list[Path] | None,
    typer.Option(
        "--in-calibration-gold-csv",
        help="Gold CSV used during threshold calibration/training. May be passed multiple times.",
    ),
]


def _settings(
    output_dir: Path,
    markdown_report: Path,
    latex_tables_dir: Path,
    cv_folds: int,
    cv_seed: int,
) -> IntegrationAssessmentSettings:
    return IntegrationAssessmentSettings(
        output_dir=output_dir,
        markdown_report=markdown_report,
        latex_tables_dir=latex_tables_dir,
        cv_folds=cv_folds,
        cv_seed=cv_seed,
    )


def _run(
    *,
    gold_csv: list[Path] | None,
    in_calibration_gold_csv: list[Path] | None,
    output_dir: Path,
    markdown_report: Path,
    latex_tables_dir: Path,
    cv_folds: int,
    cv_seed: int,
) -> None:
    settings = _settings(output_dir, markdown_report, latex_tables_dir, cv_folds, cv_seed)
    payload = run_assessment(
        settings,
        gold_csvs=gold_csv,
        in_calibration_gold_csvs=in_calibration_gold_csv,
    )
    write_markdown_report(payload, settings.markdown_report)
    write_latex_tables(payload, settings.latex_tables_dir)

    typer.echo("Integration assessment completed.")
    typer.echo(f"Metrics: {settings.output_dir / 'integration_assessment_metrics.json'}")
    typer.echo(f"Confusion: {settings.output_dir / 'integration_er_confusion.csv'}")
    typer.echo(f"Errors: {settings.output_dir / 'integration_errors.csv'}")
    typer.echo(f"Geocoding: {settings.output_dir / 'integration_geocoding_error.csv'}")
    typer.echo(f"Markdown report: {settings.markdown_report}")
    typer.echo(f"LaTeX tables: {settings.latex_tables_dir}")


def export_unlabeled_sample(
    *,
    collections,
    settings: IntegrationAssessmentSettings,
    output: Path,
    sample_size: int,
    source: str = "all",
    chain_filter: str = "all",
    seed: int = 42,
    gold_csv: list[Path] | None = None,
    in_calibration_gold_csv: list[Path] | None = None,
) -> int:
    """Write an unlabeled candidate sample, excluding existing gold IDs."""
    labeled_ids = gold_ids(load_gold_rows(settings.resolve_gold_paths(gold_csv)))
    labeled_ids.update(
        gold_ids(
            load_gold_rows(settings.resolve_in_calibration_gold_paths(in_calibration_gold_csv))
        )
    )
    query = {"label": {"$in": ["MATCH", "NON_MATCH", "UNCERTAIN"]}, "score": {"$ne": None}}
    candidates = [
        candidate
        for candidate in collections.candidates.find(query)
        if str(candidate.get("_id")) not in labeled_ids
    ]
    sample = select_calibration_sample(
        candidates,
        sample_size=sample_size,
        source=source,
        chain_filter=chain_filter,
        seed=seed,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CALIBRATION_COLUMNS)
        writer.writeheader()
        for candidate in sample:
            google_doc = _find_google(collections.google, candidate.get("google_id"))
            source_doc = _find_source(
                collections.tripadvisor,
                collections.thefork,
                str(candidate.get("source")),
                str(candidate.get("source_id")),
            )
            writer.writerow(_row_for_candidate(candidate, google_doc, source_doc))

    return len(sample)


@app.callback()
def main(
    ctx: typer.Context,
    gold_csv: GoldOption = None,
    in_calibration_gold_csv: InCalibrationGoldOption = None,
    output_dir: Path = typer.Option(
        Path("data/quality/integration_assessment"),
        help="JSON/CSV output directory.",
    ),
    markdown_report: Path = typer.Option(
        Path("docs/post-integration-assessment.md"),
        help="Generated Markdown report path.",
    ),
    latex_tables_dir: Path = typer.Option(
        Path("report/post_integration/tables"),
        help="Directory for generated LaTeX tables.",
    ),
    cv_folds: int = typer.Option(5, help="Cross-validation fold count."),
    cv_seed: int = typer.Option(42, help="Cross-validation random seed."),
) -> None:
    """Run `assess` when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        _run(
            gold_csv=gold_csv,
            in_calibration_gold_csv=in_calibration_gold_csv,
            output_dir=output_dir,
            markdown_report=markdown_report,
            latex_tables_dir=latex_tables_dir,
            cv_folds=cv_folds,
            cv_seed=cv_seed,
        )


@app.command()
def assess(
    gold_csv: GoldOption = None,
    in_calibration_gold_csv: InCalibrationGoldOption = None,
    output_dir: Path = typer.Option(
        Path("data/quality/integration_assessment"),
        help="JSON/CSV output directory.",
    ),
    markdown_report: Path = typer.Option(
        Path("docs/post-integration-assessment.md"),
        help="Generated Markdown report path.",
    ),
    latex_tables_dir: Path = typer.Option(
        Path("report/post_integration/tables"),
        help="Directory for generated LaTeX tables.",
    ),
    cv_folds: int = typer.Option(5, help="Cross-validation fold count."),
    cv_seed: int = typer.Option(42, help="Cross-validation random seed."),
) -> None:
    """Compute all post-integration metrics and write artifacts."""
    _run(
        gold_csv=gold_csv,
        in_calibration_gold_csv=in_calibration_gold_csv,
        output_dir=output_dir,
        markdown_report=markdown_report,
        latex_tables_dir=latex_tables_dir,
        cv_folds=cv_folds,
        cv_seed=cv_seed,
    )


@app.command("export-sample")
def export_sample(
    output: Path = typer.Option(
        Path("data/quality/integration_assessment/integration_gold_expand.csv"),
        help="CSV path for additional hand-labeling rows.",
    ),
    sample_size: int = typer.Option(200, min=1, help="Number of candidates to export."),
    source: str = typer.Option("all", help="Source filter: all, tripadvisor, or thefork."),
    chain_filter: str = typer.Option("all", help="Chain filter: all, chain, or non_chain."),
    seed: int = typer.Option(42, help="Deterministic sample seed."),
    gold_csv: GoldOption = None,
    in_calibration_gold_csv: InCalibrationGoldOption = None,
) -> None:
    """Export unlabeled ER candidates for expanding the gold standard."""
    settings = IntegrationAssessmentSettings()
    collections = open_collections(settings)
    exported = export_unlabeled_sample(
        collections=collections,
        settings=settings,
        output=output,
        sample_size=sample_size,
        source=source,
        chain_filter=chain_filter,
        seed=seed,
        gold_csv=gold_csv,
        in_calibration_gold_csv=in_calibration_gold_csv,
    )
    typer.echo(f"Exported {exported} unlabeled candidates to {output}")
