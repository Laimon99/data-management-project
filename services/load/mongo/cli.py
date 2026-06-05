from __future__ import annotations

import json
import logging
from dataclasses import asdict

import typer
from pymongo.errors import PyMongoError

from .config import LoaderSettings
from .loader import LoadReport, load_source, open_collection
from .sources import resolve

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.command()
def load(
    source: str = typer.Argument(
        ...,
        help="Source to load: 'google', 'tripadvisor', 'thefork', or 'all'.",
    ),
    reset: bool = typer.Option(
        False,
        "--reset",
        "--drop",
        help="Empty the destination collection before loading (destructive).",
    ),
) -> None:
    """Load raw source files from data/raw into MongoDB (raw passthrough)."""

    _configure_logging()

    try:
        specs = resolve(source)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from None

    # Fail fast on any missing raw file before touching MongoDB.
    missing = [spec for spec in specs if not spec.raw_file.exists()]
    if missing:
        for spec in missing:
            typer.echo(f"Raw file for source '{spec.name}' not found: {spec.raw_file}", err=True)
        raise typer.Exit(code=1)

    settings = LoaderSettings()
    reports: list[LoadReport] = []
    for spec in specs:
        client = None
        try:
            client, collection = open_collection(settings, spec)
            report = load_source(spec, collection, reset=reset)
        except PyMongoError as exc:
            typer.echo(f"MongoDB error while loading '{spec.name}': {exc}", err=True)
            raise typer.Exit(code=1) from None
        except ValueError as exc:
            typer.echo(f"Error loading '{spec.name}': {exc}", err=True)
            raise typer.Exit(code=1) from None
        finally:
            if client is not None:
                client.close()
        reports.append(report)
        typer.echo(json.dumps(asdict(report), indent=2))

    if len(reports) > 1:
        total = {
            "sources": len(reports),
            "read": sum(r.read for r in reports),
            "inserted": sum(r.inserted for r in reports),
            "modified": sum(r.modified for r in reports),
            "skipped": sum(r.skipped for r in reports),
        }
        typer.echo(json.dumps({"total": total}, indent=2))
