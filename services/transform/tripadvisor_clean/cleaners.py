"""Pure cleaning functions for raw Tripadvisor records.

No MongoDB, no network, no file I/O — every function takes and returns plain
Python values, so they are unit-testable in isolation and reusable by the other
sources later. Sentinel/`NaN` semantics are shared with ``geocode.is_nan`` to
keep a single definition.
"""

from __future__ import annotations

import re
from typing import Any

from .geocode import is_nan

_WS_RE = re.compile(r"\s+")
_LOCATION_ID_RE = re.compile(r"-d(\d+)-")  # TripAdvisor location id token in the URL
_CAP_RE = re.compile(r"\b(\d{5})\b")  # Italian postal code (CAP)
_RATING_RE = re.compile(r"\d+(?:\.\d+)?")
_INT_TOKEN_RE = re.compile(r"\d[\d.]*")  # an integer possibly with Italian thousands dots
_COUNTRY_RE = re.compile(r"\b(italia|italy)\b", re.IGNORECASE)


def nan_to_none(value: Any) -> Any:
    """Coerce the ``"NaN"`` sentinel / empty / None to a real ``None``."""
    return None if is_nan(value) else value


def parse_rating(value: Any) -> float | None:
    """Parse an Italian decimal-comma rating (e.g. ``"5,0"``) into a float.

    Accepts an already-numeric value and defensively a decimal-point string.
    Out-of-range (outside ``[0, 5]``) or unparseable values become ``None``.
    """
    if is_nan(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        rating = float(value)
    else:
        match = _RATING_RE.search(str(value).strip().replace(",", "."))
        if not match:
            return None
        try:
            rating = float(match.group(0))
        except ValueError:
            return None
    return rating if 0.0 <= rating <= 5.0 else None


def parse_review_count(value: Any) -> int | None:
    """Extract the integer review count from strings like ``"(1.234 recensioni)"``.

    Drops Italian thousands separators. Unparseable values become ``None``.
    """
    if is_nan(value):
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    match = _INT_TOKEN_RE.search(str(value))
    if not match:
        return None
    digits = match.group(0).replace(".", "")
    return int(digits) if digits.isdigit() else None


def extract_location_id(source_url: Any) -> str | None:
    """Extract TripAdvisor's stable location id (the ``-d<n>-`` token) from the URL.

    e.g. ``…-d28119476-Reviews-…`` -> ``"28119476"``. This is TripAdvisor's canonical
    venue id — unique per restaurant, stable across slug/locale changes — so it is a
    good join/blocking key for entity resolution. Returns ``None`` if no token is found.
    The collection ``_id`` remains ``source_url``; this is stored as a regular field.
    """
    if is_nan(source_url):
        return None
    match = _LOCATION_ID_RE.search(str(source_url))
    return match.group(1) if match else None


def normalize_name(value: Any) -> str | None:
    """Trim and collapse internal whitespace; whitespace-only/`NaN` -> None."""
    if is_nan(value):
        return None
    cleaned = _WS_RE.sub(" ", str(value)).strip()
    return cleaned or None


def normalize_address(value: Any) -> str | None:
    """Trim, collapse whitespace, and standardize comma separators."""
    if is_nan(value):
        return None
    cleaned = _WS_RE.sub(" ", str(value)).strip()
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned).strip(" ,")
    return cleaned or None


def extract_address_parts(value: Any) -> dict[str, str | None]:
    """Best-effort structured extraction of postal_code / street / city.

    Conservative: any sub-field that cannot be confidently parsed is ``None``.
    The normalized full ``address`` remains the source of truth.
    """
    parts: dict[str, str | None] = {"postal_code": None, "street": None, "city": None}
    text = normalize_address(value)
    if not text:
        return parts

    cap = _CAP_RE.search(text)
    if cap:
        parts["postal_code"] = cap.group(1)
        street = text[: cap.start()].strip().rstrip(",").strip()
        parts["street"] = street or None
        tail = text[cap.end() :].strip().lstrip(",").strip()
        if tail:
            city = tail.split(",")[0]
            city = _COUNTRY_RE.sub("", city).strip(" ,")
            parts["city"] = city or None
    else:
        # No CAP found: best-effort street = first comma-separated chunk.
        parts["street"] = text.split(",")[0].strip() or None
    return parts


def clean_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Clean one raw record (pure).

    Coerces every field's ``"NaN"`` sentinel to ``None``, then overlays the typed
    / normalized fields and the structured address parts. Does **not** touch
    ``_id``/keying or geocoding — that is the transform layer's job.
    """
    cleaned: dict[str, Any] = {key: nan_to_none(value) for key, value in raw.items()}
    cleaned["restaurant_name"] = normalize_name(raw.get("restaurant_name"))
    cleaned["address"] = normalize_address(raw.get("address"))
    cleaned["rating"] = parse_rating(raw.get("rating"))
    cleaned["total_review"] = parse_review_count(raw.get("total_review"))
    cleaned["ta_location_id"] = extract_location_id(raw.get("source_url"))
    cleaned.update(extract_address_parts(raw.get("address")))
    return cleaned
