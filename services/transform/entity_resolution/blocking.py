from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .preprocess import name_tokens

EARTH_RADIUS_M = 6_371_008.8
METRES_PER_DEGREE_LAT = 111_320.0


@dataclass(frozen=True)
class BlockedPair:
    google: dict[str, Any]
    source: dict[str, Any]
    block_source: str


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def coordinates(doc: dict[str, Any]) -> tuple[float, float] | None:
    lat = _to_float(doc.get("latitude"))
    lon = _to_float(doc.get("longitude"))
    if lat is None or lon is None:
        return None
    return lat, lon


def has_coordinates(doc: dict[str, Any]) -> bool:
    return coordinates(doc) is not None


def haversine_distance_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Return Haversine distance in metres."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _cell_range(value: float, delta: float, cell_deg: float) -> range:
    return range(
        math.floor((value - delta) / cell_deg),
        math.floor((value + delta) / cell_deg) + 1,
    )


def geo_block(
    google_docs: list[dict[str, Any]],
    source_docs: list[dict[str, Any]],
    radius_m: float,
) -> list[BlockedPair]:
    """Generate geo-proximity candidate pairs using a grid/bounding-box prefilter."""
    cell_deg = max(radius_m / METRES_PER_DEGREE_LAT, 0.0001)
    index: dict[tuple[int, int], list[tuple[dict[str, Any], float, float]]] = defaultdict(list)

    for google in google_docs:
        coords = coordinates(google)
        if coords is None:
            continue
        lat, lon = coords
        index[(math.floor(lat / cell_deg), math.floor(lon / cell_deg))].append((google, lat, lon))

    pairs: list[BlockedPair] = []
    for source in source_docs:
        coords = coordinates(source)
        if coords is None:
            continue
        src_lat, src_lon = coords
        lat_delta = radius_m / METRES_PER_DEGREE_LAT
        lon_scale = max(math.cos(math.radians(src_lat)), 0.01)
        lon_delta = radius_m / (METRES_PER_DEGREE_LAT * lon_scale)

        for lat_cell in _cell_range(src_lat, lat_delta, cell_deg):
            for lon_cell in _cell_range(src_lon, lon_delta, cell_deg):
                for google, google_lat, google_lon in index.get((lat_cell, lon_cell), []):
                    distance = haversine_distance_m(google_lat, google_lon, src_lat, src_lon)
                    if distance <= radius_m:
                        pairs.append(BlockedPair(google, source, "geo"))
    return pairs


def _postal_code(doc: dict[str, Any]) -> str | None:
    value = doc.get("postal_code")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _doc_identity(doc: dict[str, Any]) -> Any:
    return doc.get("place_id") or doc.get("_id") or id(doc)


def _source_name(doc: dict[str, Any]) -> Any:
    return doc.get("restaurant_name") or doc.get("name")


def postal_name_block(
    google_docs: list[dict[str, Any]],
    ta_no_coords: list[dict[str, Any]],
) -> list[BlockedPair]:
    """Generate TA fallback pairs by same postal code and one shared long name token."""
    google_by_postal_token: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for google in google_docs:
        postal = _postal_code(google)
        if postal is None:
            continue
        for token in name_tokens(google.get("name")):
            google_by_postal_token[postal][token].append(google)

    pairs: list[BlockedPair] = []
    for source in ta_no_coords:
        postal = _postal_code(source)
        if postal is None:
            continue
        seen_google: set[Any] = set()
        for token in name_tokens(_source_name(source)):
            for google in google_by_postal_token.get(postal, {}).get(token, []):
                google_id = _doc_identity(google)
                if google_id in seen_google:
                    continue
                seen_google.add(google_id)
                pairs.append(BlockedPair(google, source, "postal_code"))
    return pairs
