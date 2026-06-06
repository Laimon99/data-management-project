from __future__ import annotations

import json
import logging
from dataclasses import asdict

import typer
from geopy.geocoders import Nominatim
from pymongo.errors import PyMongoError

from .config import CleanSettings
from .transform import clean_collection, open_transform_collections

app = typer.Typer(add_completion=False, no_args_is_help=False)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.command()
def clean(
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Only process the first N records (test slice)."
    ),
    skip_geocode: bool = typer.Option(
        False, "--skip-geocode", help="Clean only; make no Nominatim calls, keep existing coords."
    ),
    reset: bool = typer.Option(
        False, "--reset", "--drop", help="Empty the destination collection first (destructive)."
    ),
    delay: float | None = typer.Option(
        None, "--delay", help="Seconds between geocode requests (>= 1s per Nominatim ToS)."
    ),
    timeout: int | None = typer.Option(None, "--timeout", help="Per-request HTTP timeout (s)."),
) -> None:
    """Clean raw Tripadvisor records and geocode them into restaurants_clean_tripadvisor."""

    _configure_logging()

    if delay is not None and delay < 1.0:
        raise typer.BadParameter(
            "--delay must be >= 1s to respect the Nominatim usage policy.",
            param_hint="--delay",
        )

    settings = CleanSettings()
    if delay is not None:
        settings.delay_seconds = delay
    if timeout is not None:
        settings.timeout = timeout

    client = None
    try:
        client, source, dest = open_transform_collections(settings)
        geocoder = None if skip_geocode else Nominatim(user_agent=settings.user_agent)
        report = clean_collection(
            source,
            dest,
            settings,
            reset=reset,
            skip_geocode=skip_geocode,
            limit=limit,
            geocoder=geocoder,
        )
    except PyMongoError as exc:
        typer.echo(f"MongoDB error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        if client is not None:
            client.close()

    typer.echo(json.dumps(asdict(report), indent=2))
