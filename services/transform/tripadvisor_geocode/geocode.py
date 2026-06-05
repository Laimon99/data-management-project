"""Enrich a Tripadvisor JSON dataset with latitude/longitude via Nominatim.

Uses the free OpenStreetMap Nominatim service through ``geopy`` — no API key,
no cost. Coordinates enable proximity blocking for entity resolution and the
geographic queries on the unified dataset.

Ported and adapted (English, parametrised, ruff-clean) from Edoardo's original
``geocode.py`` on the ``tripadvisor-geocoding-enrichment`` branch.
"""

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from geopy.exc import GeocoderServiceError, GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import Nominatim

from .config import NAN_VALUE, GeocodeSettings

logger = logging.getLogger(__name__)


@dataclass
class GeocodeReport:
    """Summary of a geocoding run."""

    total: int = 0
    found: int = 0
    not_found: int = 0
    skipped: int = 0


def is_nan(value: object) -> bool:
    """Return True if the value is absent, None, or the string 'NaN'."""
    if value is None:
        return True
    return str(value).strip().lower() == "nan"


def reorder_with_coords(restaurant: dict, lat: str, lon: str) -> OrderedDict:
    """Insert latitude/longitude right after 'address', preserving key order.

    Falls back to appending at the end if the record has no 'address' key.
    """
    result: OrderedDict = OrderedDict()
    for key, value in restaurant.items():
        result[key] = value
        if key == "address":
            result["latitude"] = lat
            result["longitude"] = lon
    if "latitude" not in result:
        result["latitude"] = lat
        result["longitude"] = lon
    return result


def geocode_address(
    geocoder: Nominatim,
    address: str,
    *,
    timeout: int,
    max_retries: int,
    delay_seconds: float,
) -> tuple[str, str]:
    """Geocode a single address with retry/back-off on transient errors.

    Returns (latitude, longitude) as strings, or (NaN, NaN) when not found.
    """
    for attempt in range(1, max_retries + 1):
        try:
            location = geocoder.geocode(address, timeout=timeout)
            if location:
                return str(location.latitude), str(location.longitude)
            return NAN_VALUE, NAN_VALUE  # address not found
        except GeocoderTimedOut:
            logger.warning("Timeout (attempt %d/%d) - %r", attempt, max_retries, address)
            if attempt < max_retries:
                time.sleep(delay_seconds * attempt)  # progressive back-off
        except (GeocoderServiceError, GeocoderUnavailable) as exc:
            logger.warning("Network error (attempt %d/%d): %s", attempt, max_retries, exc)
            if attempt < max_retries:
                time.sleep(delay_seconds * attempt)
        except Exception as exc:  # noqa: BLE001 - network/parser are unpredictable
            logger.error("Unexpected exception while geocoding %r: %s", address, exc)
            break

    return NAN_VALUE, NAN_VALUE


def geocode_dataset(
    input_path: Path,
    output_path: Path,
    settings: GeocodeSettings,
    *,
    limit: int | None = None,
) -> GeocodeReport:
    """Read restaurants from ``input_path``, geocode them, write to ``output_path``.

    ``limit`` caps the number of records processed (useful for a quick test slice
    instead of the full multi-hour Nominatim run).
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with input_path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, list):
        raise ValueError("Input JSON must be an array of restaurant objects.")

    if limit is not None:
        data = data[:limit]

    total = len(data)
    logger.info("Loaded %d restaurants from %s", total, input_path)
    logger.info(
        "Delay between requests: %ss | timeout: %ss",
        settings.delay_seconds,
        settings.timeout,
    )

    geocoder = Nominatim(user_agent=settings.user_agent)

    enriched: list[OrderedDict] = []
    for idx, restaurant in enumerate(data, start=1):
        name = restaurant.get("restaurant_name", f"<record #{idx}>")
        address = restaurant.get("address", NAN_VALUE)

        if is_nan(address):
            lat, lon = NAN_VALUE, NAN_VALUE
            logger.info("[%d/%d] SKIP %r -> address NaN", idx, total, name)
        else:
            lat, lon = geocode_address(
                geocoder,
                address,
                timeout=settings.timeout,
                max_retries=settings.max_retries,
                delay_seconds=settings.delay_seconds,
            )
            status = "OK" if not is_nan(lat) and not is_nan(lon) else "NOT FOUND"
            logger.info("[%d/%d] %s %r -> lat=%s lon=%s", idx, total, status, name, lat, lon)
            # Respect the Nominatim rate limit (1 req/s).
            time.sleep(settings.delay_seconds)

        enriched.append(reorder_with_coords(restaurant, lat, lon))

    # Write atomically: a crash mid-dump must not leave a truncated final file.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(enriched, fh, ensure_ascii=False, indent=4)
    tmp_path.replace(output_path)

    # Buckets are mutually exclusive: a skipped (NaN-address) record always has
    # NaN coords, so it never also counts as found/not_found.
    report = GeocodeReport(total=total)
    for record in enriched:
        if is_nan(record.get("address", NAN_VALUE)):
            report.skipped += 1
        elif not is_nan(record.get("latitude")) and not is_nan(record.get("longitude")):
            report.found += 1
        else:
            report.not_found += 1

    logger.info(
        "Done -> %s | found=%d not_found=%d skipped=%d total=%d",
        output_path,
        report.found,
        report.not_found,
        report.skipped,
        report.total,
    )
    return report
