from __future__ import annotations

import json
import logging
from dataclasses import asdict
from enum import Enum

import typer
from pydantic import ValidationError
from pymongo.errors import PyMongoError

from .config import ERSettings
from .transform import open_transform_collections, resolve_collections

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
def resolve(
    source: SourceOption = typer.Option(
        SourceOption.all,
        "--source",
        case_sensitive=False,
        help="Source pairing to resolve: tripadvisor, thefork, or all.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Build and score candidates without writing to MongoDB.",
    ),
    replace_destination: bool = typer.Option(
        False,
        "--replace-destination",
        help=(
            "Delete existing ER candidates for the selected source scope before writing. "
            "With --source all, rewrites all ER candidates."
        ),
    ),
    dmin: float | None = typer.Option(
        None,
        "--dmin",
        help="Runtime override for the NON_MATCH threshold.",
    ),
    dmax: float | None = typer.Option(
        None,
        "--dmax",
        help="Runtime override for the MATCH threshold.",
    ),
    dmin_tripadvisor: float | None = typer.Option(
        None,
        "--dmin-tripadvisor",
        help="Tripadvisor override for the NON_MATCH threshold; defaults to --dmin.",
    ),
    dmax_tripadvisor: float | None = typer.Option(
        None,
        "--dmax-tripadvisor",
        help="Tripadvisor override for the MATCH threshold; defaults to --dmax.",
    ),
    dmin_thefork: float | None = typer.Option(
        None,
        "--dmin-thefork",
        help="TheFork override for the NON_MATCH threshold; defaults to --dmin.",
    ),
    dmax_thefork: float | None = typer.Option(
        None,
        "--dmax-thefork",
        help="TheFork override for the MATCH threshold; defaults to --dmax.",
    ),
    dmin_chain_tripadvisor: float | None = typer.Option(
        None,
        "--dmin-chain-tripadvisor",
        help=(
            "Tripadvisor chain-brand override for the NON_MATCH threshold; "
            "defaults to --dmin-tripadvisor."
        ),
    ),
    dmax_chain_tripadvisor: float | None = typer.Option(
        None,
        "--dmax-chain-tripadvisor",
        help=(
            "Tripadvisor chain-brand override for the MATCH threshold; "
            "defaults to --dmax-tripadvisor."
        ),
    ),
    dmin_chain_thefork: float | None = typer.Option(
        None,
        "--dmin-chain-thefork",
        help=(
            "TheFork chain-brand override for the NON_MATCH threshold; "
            "defaults to --dmin-thefork."
        ),
    ),
    dmax_chain_thefork: float | None = typer.Option(
        None,
        "--dmax-chain-thefork",
        help=(
            "TheFork chain-brand override for the MATCH threshold; " "defaults to --dmax-thefork."
        ),
    ),
) -> None:
    """Generate Google-anchored ER candidates into entity_resolution_candidates."""

    _configure_logging()

    client = None
    try:
        settings = ERSettings(
            **{
                key: value
                for key, value in {
                    "dmin": dmin,
                    "dmax": dmax,
                    "dmin_tripadvisor": dmin_tripadvisor,
                    "dmax_tripadvisor": dmax_tripadvisor,
                    "dmin_thefork": dmin_thefork,
                    "dmax_thefork": dmax_thefork,
                    "dmin_chain_tripadvisor": dmin_chain_tripadvisor,
                    "dmax_chain_tripadvisor": dmax_chain_tripadvisor,
                    "dmin_chain_thefork": dmin_chain_thefork,
                    "dmax_chain_thefork": dmax_chain_thefork,
                }.items()
                if value is not None
            }
        )
        client, google, tripadvisor, thefork, destination = open_transform_collections(settings)
        report = resolve_collections(
            google,
            tripadvisor,
            thefork,
            destination,
            settings,
            source=source.value,
            dry_run=dry_run,
            replace_destination=replace_destination,
        )
    except PyMongoError as exc:
        typer.echo(f"MongoDB error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except (ValidationError, ValueError) as exc:
        typer.echo(f"Error resolving candidates: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        if client is not None:
            client.close()

    typer.echo(json.dumps(asdict(report), indent=2))
