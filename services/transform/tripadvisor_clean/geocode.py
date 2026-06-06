"""Geocoding enrichment for the Tripadvisor transform (Nominatim/OpenStreetMap).

Absorbed from the former ``transform.tripadvisor_geocode`` service: the proven
``geocode_address`` retry/back-off and ``is_nan`` semantics are preserved. The
file-based I/O of the old service is gone — geocoding now runs in-memory on a
cleaned record as a sub-step of the transform (see ``transform.py``).

Free of MongoDB and file I/O so it is unit-testable with a stubbed geocoder.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from geopy.exc import GeocoderServiceError, GeocoderTimedOut, GeocoderUnavailable

logger = logging.getLogger(__name__)

# Sentinel string the raw scraper uses for missing values.
NAN_VALUE = "NaN"


def is_nan(value: object) -> bool:
    """Return True if the value is absent: None, empty/whitespace, or 'NaN'."""
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.lower() == "nan"


def build_query(record: dict[str, Any]) -> str | dict[str, str] | None:
    """Build a Nominatim query for a cleaned record.

    Prefers a structured query (street + postcode + city + country) when the
    cleaner extracted those parts — structured queries are more accurate than
    free-text. Falls back to the normalized free-text ``address``.
    """
    street = record.get("street")
    postal_code = record.get("postal_code")
    if not is_nan(street) or not is_nan(postal_code):
        query: dict[str, str] = {"country": "Italy"}
        if not is_nan(street):
            query["street"] = str(street)
        if not is_nan(postal_code):
            query["postalcode"] = str(postal_code)
        city = record.get("city")
        query["city"] = str(city) if not is_nan(city) else "Milano"
        return query
    address = record.get("address")
    return None if is_nan(address) else str(address)


def geocode_address(
    geocoder: Any,
    query: str | dict[str, str],
    *,
    timeout: int,
    max_retries: int,
    delay_seconds: float,
) -> tuple[float | None, float | None]:
    """Geocode a single address/structured query with retry/back-off.

    Returns (latitude, longitude) as floats, or (None, None) when not found.
    """
    for attempt in range(1, max_retries + 1):
        try:
            location = geocoder.geocode(query, timeout=timeout)
            if location:
                return float(location.latitude), float(location.longitude)
            return None, None  # query had no match
        except GeocoderTimedOut:
            logger.warning("Timeout (attempt %d/%d) - %r", attempt, max_retries, query)
            if attempt < max_retries:
                time.sleep(delay_seconds * attempt)  # progressive back-off
        except (GeocoderServiceError, GeocoderUnavailable) as exc:
            logger.warning("Network error (attempt %d/%d): %s", attempt, max_retries, exc)
            if attempt < max_retries:
                time.sleep(delay_seconds * attempt)
        except Exception as exc:  # noqa: BLE001 - network/parser errors are unpredictable
            logger.error("Unexpected exception while geocoding %r: %s", query, exc)
            break

    return None, None


def geocode_one(
    geocoder: Any,
    record: dict[str, Any],
    settings: Any,
) -> tuple[float | None, float | None]:
    """Geocode one cleaned record.

    A null/`NaN` cleaned address returns (None, None) without a network call.
    The per-request rate-limit sleep is the caller's responsibility (so it only
    happens on real calls).
    """
    if is_nan(record.get("address")):
        return None, None
    query = build_query(record)
    if query is None:
        return None, None
    return geocode_address(
        geocoder,
        query,
        timeout=settings.timeout,
        max_retries=settings.max_retries,
        delay_seconds=settings.delay_seconds,
    )
