from __future__ import annotations

import json
import logging
from dataclasses import asdict

import typer
from pymongo.errors import PyMongoError

from .config import ClickHouseLoaderSettings
from .loader import LoadReport, load_target, open_clickhouse, open_mongo
from .targets import resolve

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.command()
def load(
    target: str = typer.Argument(
        ...,
        help=(
            "Target to load: 'integrated', 'clean_google', 'clean_tripadvisor',"
            " 'clean_thefork', or 'all'."
        ),
    ),
    recreate: bool = typer.Option(
        False,
        "--recreate",
        help=(
            "DROP and recreate each target table before loading. Required after a schema"
            " change (new/changed columns): a plain reload only does CREATE IF NOT EXISTS,"
            " so an existing table would keep its old schema."
        ),
    ),
) -> None:
    """Load cleaned and integrated MongoDB collections into ClickHouse (truncate + reload)."""

    _configure_logging()

    try:
        specs = resolve(target)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from None

    settings = ClickHouseLoaderSettings()
    reports: list[LoadReport] = []

    # Open one ClickHouse client for all targets.
    try:
        ch_client = open_clickhouse(settings)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"ClickHouse connection error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    for spec in specs:
        mongo_client = None
        try:
            mongo_client, mongo_collection = open_mongo(settings, spec.mongo_collection)
            report = load_target(spec, mongo_collection, ch_client, recreate=recreate)
        except PyMongoError as exc:
            typer.echo(f"MongoDB error while loading '{spec.name}': {exc}", err=True)
            raise typer.Exit(code=1) from None
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"Error loading '{spec.name}': {exc}", err=True)
            raise typer.Exit(code=1) from None
        finally:
            if mongo_client is not None:
                mongo_client.close()
        reports.append(report)
        typer.echo(json.dumps(asdict(report), indent=2))

    if len(reports) > 1:
        total = {
            "targets": len(reports),
            "read": sum(r.read for r in reports),
            "inserted": sum(r.inserted for r in reports),
            "skipped": sum(r.skipped for r in reports),
        }
        typer.echo(json.dumps({"total": total}, indent=2))
