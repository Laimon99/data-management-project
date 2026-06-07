"""Backfill Tripadvisor clean coordinates from the old geocoded JSON export.

Temporary bridge for the Nominatim throttle window: this updates only the
coordinate fields that the normal transform owns. It deliberately does not create
clean documents; run ``tripadvisor-clean --skip-geocode`` first if the clean
collection is empty.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from pymongo.errors import PyMongoError

from . import geocode as geocode_mod
from .config import CleanSettings
from .transform import open_transform_collections

COORD_FLAGS = {"geocode_not_found", "missing_coordinates"}
DEFAULT_INPUT = Path("tripadvisor_scraper_results_geocoded.json")


@dataclass
class BackfillReport:
    input_path: str
    destination_collection: str
    read: int = 0
    missing_key: int = 0
    invalid_record: int = 0
    invalid_coordinates: int = 0
    duplicate_key: int = 0
    usable_coordinates: int = 0
    missing_clean_doc: int = 0
    skipped_existing_coordinates: int = 0
    would_update: int = 0
    updated: int = 0
    modified: int = 0
    dry_run: bool = False
    overwrite: bool = False


def _parse_coordinate(value: Any, *, kind: str) -> float | None:
    if geocode_mod.is_nan(value):
        return None
    try:
        coord = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(coord):
        return None
    if kind == "latitude" and not -90 <= coord <= 90:
        return None
    if kind == "longitude" and not -180 <= coord <= 180:
        return None
    return coord


def _load_coordinates(path: Path, report: BackfillReport) -> dict[str, tuple[float, float]]:
    with path.open(encoding="utf-8") as fh:
        payload = json.load(fh)

    if not isinstance(payload, list):
        raise ValueError("Input JSON must contain a list of Tripadvisor restaurant objects.")

    coordinates: dict[str, tuple[float, float]] = {}
    for item in payload:
        report.read += 1
        if not isinstance(item, dict):
            report.invalid_record += 1
            continue

        key = item.get("source_url")
        if geocode_mod.is_nan(key):
            report.missing_key += 1
            continue
        key = str(key)

        lat = _parse_coordinate(item.get("latitude"), kind="latitude")
        lon = _parse_coordinate(item.get("longitude"), kind="longitude")
        if lat is None or lon is None:
            report.invalid_coordinates += 1
            continue

        if key in coordinates:
            report.duplicate_key += 1
        coordinates[key] = (lat, lon)

    report.usable_coordinates = len(coordinates)
    return coordinates


def _clean_flags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [flag for flag in value if flag not in COORD_FLAGS]


def backfill_collection(
    collection: Any,
    coordinates: dict[str, tuple[float, float]],
    report: BackfillReport,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> BackfillReport:
    report.dry_run = dry_run
    report.overwrite = overwrite

    projection = {"latitude": 1, "longitude": 1, "flags": 1}
    for source_url, (lat, lon) in coordinates.items():
        doc = collection.find_one({"_id": source_url}, projection)
        if doc is None:
            report.missing_clean_doc += 1
            continue

        has_coords = doc.get("latitude") is not None and doc.get("longitude") is not None
        if has_coords and not overwrite:
            report.skipped_existing_coordinates += 1
            continue

        report.would_update += 1
        if dry_run:
            continue

        result = collection.update_one(
            {"_id": source_url},
            {
                "$set": {
                    "latitude": lat,
                    "longitude": lon,
                    "has_coordinates": True,
                    "flags": _clean_flags(doc.get("flags")),
                    "_coordinates_backfilled_at": datetime.now(UTC),
                }
            },
        )
        report.updated += result.matched_count
        report.modified += result.modified_count

    return report


def main(
    input_path: Path = typer.Argument(
        DEFAULT_INPUT,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Old geocoded Tripadvisor JSON export.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would be updated."),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Replace existing non-null coordinates instead of filling only missing coords.",
    ),
) -> None:
    """Backfill clean Tripadvisor latitude/longitude from a geocoded JSON file."""

    settings = CleanSettings()
    report = BackfillReport(
        input_path=str(input_path),
        destination_collection=settings.destination_collection,
    )

    try:
        coordinates = _load_coordinates(input_path, report)
        client, _source, destination = open_transform_collections(settings)
        try:
            report = backfill_collection(
                destination,
                coordinates,
                report,
                dry_run=dry_run,
                overwrite=overwrite,
            )
        finally:
            client.close()
    except (OSError, ValueError) as exc:
        typer.echo(f"Backfill error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except PyMongoError as exc:
        typer.echo(f"MongoDB error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(json.dumps(asdict(report), indent=2))


if __name__ == "__main__":
    typer.run(main)
