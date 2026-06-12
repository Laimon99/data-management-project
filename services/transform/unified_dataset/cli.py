from __future__ import annotations

import json
import logging
from dataclasses import asdict

import typer
from pydantic import ValidationError
from pymongo.errors import PyMongoError

from .config import UnifiedSettings
from .transform import open_transform_collections, unify_collections

app = typer.Typer(add_completion=False, no_args_is_help=False)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.command()
def unify(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Build links and integrated records without writing to MongoDB.",
    ),
    replace_destination: bool = typer.Option(
        False,
        "--replace-destination",
        help="Delete existing link/integrated outputs before writing the rebuilt outputs.",
    ),
    skip_links: bool = typer.Option(
        False,
        "--skip-links",
        help="Reuse existing entity_resolution_links and rebuild only restaurants_integrated.",
    ),
    source: str = typer.Option(
        "all",
        "--source",
        help="Restrict link selection to one platform: tripadvisor, thefork, or all (default).",
    ),
) -> None:
    """Create ER links and the Google-seeded integrated restaurant collection."""

    _configure_logging()

    client = None
    try:
        settings = UnifiedSettings()
        (
            client,
            google,
            tripadvisor,
            thefork,
            candidates,
            links,
            integrated,
        ) = open_transform_collections(settings)
        report = unify_collections(
            google,
            tripadvisor,
            thefork,
            candidates,
            links,
            integrated,
            settings,
            dry_run=dry_run,
            replace_destination=replace_destination,
            skip_links=skip_links,
            source=source,
        )
    except PyMongoError as exc:
        typer.echo(f"MongoDB error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except (ValidationError, ValueError) as exc:
        typer.echo(f"Error building unified dataset: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        if client is not None:
            client.close()

    typer.echo(json.dumps(asdict(report), indent=2, default=str))
