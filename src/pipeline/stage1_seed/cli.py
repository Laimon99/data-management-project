import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import typer
from pydantic import ValidationError

from .checkpoint import DetailCheckpoint, TileCheckpoint
from .config import Settings
from .logging_setup import configure as configure_logging
from .mode_detail import run_mode_detail
from .mode_list import run_mode_list
from .places_client import PlacesClient
from .storage import make_store

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _load_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        typer.echo(
            "Error loading settings. Is DATAMAN_GOOGLE_PLACES_API_KEY set in your "
            f"environment or .env?\n{exc}",
            err=True,
        )
        raise typer.Exit(code=1) from None


def _select_neighbourhood(settings: Settings, name: str) -> Settings:
    matches = [n for n in settings.neighbourhoods if n.name == name]
    if not matches:
        valid = ", ".join(n.name for n in settings.neighbourhoods) or "(none configured)"
        typer.echo(f"Unknown neighbourhood {name!r}. Valid names: {valid}", err=True)
        raise typer.Exit(code=2)
    return settings.model_copy(update={"neighbourhoods": matches})


def _do_list(
    max_results: Optional[int],
    neighbourhood: Optional[str] = None,
    whole_city: bool = False,
    all_neighbourhoods: bool = False,
) -> None:
    selectors = [whole_city, all_neighbourhoods, neighbourhood is not None]
    if sum(bool(s) for s in selectors) > 1:
        typer.echo(
            "Use at most one of --whole-city, --all-neighbourhoods, --neighbourhood.",
            err=True,
        )
        raise typer.Exit(code=2)

    settings = _load_settings()
    if whole_city:
        scope = "city"
    elif neighbourhood is not None:
        settings = _select_neighbourhood(settings, neighbourhood)
        scope = "neighbourhoods"
    elif all_neighbourhoods:
        scope = "neighbourhoods"
    else:
        scope = "full"

    configure_logging(api_key=settings.google_places_api_key.get_secret_value())
    store = make_store(settings)
    ckpt = TileCheckpoint(settings.checkpoint_dir / "list_tiles.json")
    try:
        with PlacesClient(settings) as client:
            report = run_mode_list(
                settings, store, client, ckpt, scope=scope, max_results=max_results
            )
    finally:
        store.close()
    typer.echo(json.dumps(asdict(report), default=str, indent=2))


def _do_detail(
    place_id: Optional[str],
    place_ids_file: Optional[Path],
    enrich_all: bool,
) -> None:
    settings = _load_settings()
    configure_logging(api_key=settings.google_places_api_key.get_secret_value())
    store = make_store(settings)
    ckpt = DetailCheckpoint(settings.checkpoint_dir / "detail_done.txt")

    place_ids: Optional[list[str]]
    if place_id:
        place_ids = [place_id]
    elif place_ids_file:
        place_ids = [
            line.strip()
            for line in place_ids_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    elif enrich_all:
        place_ids = None
    else:
        typer.echo(
            "Specify --place-id, --place-ids-file, or --all to choose what to enrich.",
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        with PlacesClient(settings) as client:
            report = run_mode_detail(settings, store, client, ckpt, place_ids=place_ids)
    finally:
        store.close()
    typer.echo(json.dumps(asdict(report), default=str, indent=2))


@app.command("list")
def cmd_list(
    max_results: Optional[int] = typer.Option(
        None, "--max-results", help="Stop after this many unique venues."
    ),
    neighbourhood: Optional[str] = typer.Option(
        None,
        "--neighbourhood",
        help="Tile only this one named neighbourhood anchor.",
    ),
    whole_city: bool = typer.Option(
        False,
        "--whole-city",
        help="Tile only the whole-city circle (single centre, outer_radius_m).",
    ),
    all_neighbourhoods: bool = typer.Option(
        False,
        "--all-neighbourhoods",
        help="Tile only the neighbourhood anchors, without the whole-city circle.",
    ),
) -> None:
    """Mode 1: tile Milan and collect food venues into the seed store.

    Default (no flags) covers the whole-city circle AND all neighbourhood
    anchors, merged and deduplicated.
    """
    _do_list(max_results, neighbourhood, whole_city, all_neighbourhoods)


@app.command("detail")
def cmd_detail(
    place_id: Optional[str] = typer.Option(None, "--place-id"),
    place_ids_file: Optional[Path] = typer.Option(None, "--place-ids-file"),
    enrich_all: bool = typer.Option(False, "--all", help="Enrich every place_id in the store."),
) -> None:
    """Mode 2: enrich seed records with full Place Details."""
    _do_detail(place_id, place_ids_file, enrich_all)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    mode: Optional[str] = typer.Option(
        None,
        "--mode",
        help="Legacy alias: '--mode list' or '--mode detail'.",
    ),
    max_results: Optional[int] = typer.Option(None, "--max-results", show_default=False),
    neighbourhood: Optional[str] = typer.Option(None, "--neighbourhood", show_default=False),
    whole_city: bool = typer.Option(False, "--whole-city", show_default=False),
    all_neighbourhoods: bool = typer.Option(False, "--all-neighbourhoods", show_default=False),
    place_id: Optional[str] = typer.Option(None, "--place-id", show_default=False),
    place_ids_file: Optional[Path] = typer.Option(None, "--place-ids-file", show_default=False),
    enrich_all: bool = typer.Option(False, "--all", show_default=False),
) -> None:
    if mode is None:
        return
    if ctx.invoked_subcommand is not None:
        typer.echo("Use either '--mode list/detail' or the subcommand form, not both.", err=True)
        raise typer.Exit(code=2)
    if mode == "list":
        _do_list(max_results, neighbourhood, whole_city, all_neighbourhoods)
    elif mode == "detail":
        _do_detail(place_id, place_ids_file, enrich_all)
    else:
        typer.echo(f"Unknown --mode {mode!r}; use 'list' or 'detail'.", err=True)
        raise typer.Exit(code=2)
    raise typer.Exit(code=0)
