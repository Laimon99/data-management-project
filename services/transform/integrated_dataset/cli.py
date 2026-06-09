from __future__ import annotations

import json
import logging
from dataclasses import asdict
from enum import Enum

import typer
from pydantic import ValidationError
from pymongo.errors import PyMongoError

from .config import IntegratedSettings
from .transform import build_collections, open_integrated_collections

app = typer.Typer(add_completion=False, no_args_is_help=False)


class SourceOption(str, Enum):
    tripadvisor = "tripadvisor"
    thefork = "thefork"
    all = "all"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.command()
def build(
    source: SourceOption = typer.Option(
        SourceOption.all,
        "--source",
        case_sensitive=False,
        help="Resolved-link source scope to rebuild: tripadvisor, thefork, or all.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Select links and build the integrated report without writing to MongoDB.",
    ),
    replace_destination: bool = typer.Option(
        False,
        "--replace-destination",
        help="Delete selected source links and rebuild restaurants_integrated from scratch.",
    ),
) -> None:
    """Build entity_resolution_links and restaurants_integrated in MongoDB."""

    _configure_logging()
    settings = IntegratedSettings()
    client = None
    try:
        client, google, tripadvisor, thefork, candidates, links, integrated = (
            open_integrated_collections(settings)
        )
        report = build_collections(
            google,
            tripadvisor,
            thefork,
            candidates,
            links,
            integrated,
            settings,
            source=source.value,
            dry_run=dry_run,
            replace_destination=replace_destination,
        )
    except PyMongoError as exc:
        typer.echo(f"MongoDB error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except (ValidationError, ValueError) as exc:
        typer.echo(f"Error building integrated dataset: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        if client is not None:
            client.close()

    typer.echo(json.dumps(asdict(report), indent=2))
