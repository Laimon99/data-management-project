from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

import typer

from .config import DEFAULT_INPUT, DEFAULT_OUTPUT, GeocodeSettings
from .geocode import geocode_dataset

app = typer.Typer(add_completion=False, no_args_is_help=False)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.command()
def enrich(
    input_path: Path = typer.Option(
        DEFAULT_INPUT, "--input", "-i", help="Raw Tripadvisor results JSON to geocode."
    ),
    output_path: Path = typer.Option(
        DEFAULT_OUTPUT, "--output", "-o", help="Where to write the geocoded JSON."
    ),
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Only process the first N records (test slice)."
    ),
    delay: float | None = typer.Option(
        None, "--delay", help="Seconds between requests (>= 1s per Nominatim ToS)."
    ),
    timeout: int | None = typer.Option(None, "--timeout", help="Per-request HTTP timeout (s)."),
) -> None:
    """Enrich raw Tripadvisor records with latitude/longitude via Nominatim."""

    _configure_logging()

    settings = GeocodeSettings()
    if delay is not None:
        settings.delay_seconds = delay
    if timeout is not None:
        settings.timeout = timeout

    try:
        report = geocode_dataset(input_path, output_path, settings, limit=limit)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from None

    typer.echo(json.dumps(asdict(report), indent=2))
