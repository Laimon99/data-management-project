from __future__ import annotations

import json
import logging
from dataclasses import asdict

import typer
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
    reset: bool = typer.Option(
        False, "--reset", help="Empty the destination collection first (destructive)."
    ),
    low_review: int | None = typer.Option(
        None, "--low-review", help="Flag records with fewer than this many reviews."
    ),
    review_cap: int | None = typer.Option(
        None, "--review-cap", help="Max nested reviews kept per restaurant (default 15)."
    ),
) -> None:
    """Clean raw TheFork records into restaurants_clean_thefork (Mongo -> Mongo, no geocoding)."""

    _configure_logging()

    settings = CleanSettings()
    if low_review is not None:
        settings.low_review_threshold = low_review
    if review_cap is not None:
        settings.review_cap = review_cap

    client = None
    try:
        client, source, dest = open_transform_collections(settings)
        report = clean_collection(source, dest, settings, reset=reset, limit=limit)
    except PyMongoError as exc:
        typer.echo(f"MongoDB error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        if client is not None:
            client.close()

    typer.echo(json.dumps(asdict(report), indent=2))
