from __future__ import annotations

import math

from transform.entity_resolution.blocking import haversine_distance_m

from .constants import (
    CENTER_RADIUS_KM,
    DUOMO_LAT,
    DUOMO_LON,
    POPULAR_NEIGHBOURHOODS,
    SPARSE_REVIEW_THRESHOLD,
)


def _valid_coord(lat: float | None, lon: float | None) -> tuple[float, float] | None:
    """Return (lat, lon) only when both are finite and non-zero.

    A missing or zero coordinate (e.g. an unresolved geocode) is treated as
    absent rather than as the point (0, 0), so it is excluded from distance
    cuts instead of bucketed at distance 0.
    """
    if lat is None or lon is None:
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat_f) and math.isfinite(lon_f)):
        return None
    if lat_f == 0.0 and lon_f == 0.0:
        return None
    return lat_f, lon_f


def distance_to_duomo_km(lat: float | None, lon: float | None) -> float | None:
    """Haversine distance from Piazza del Duomo in kilometres, or None."""
    coord = _valid_coord(lat, lon)
    if coord is None:
        return None
    return haversine_distance_m(coord[0], coord[1], DUOMO_LAT, DUOMO_LON) / 1000.0


def classify_center_periphery(
    lat: float | None,
    lon: float | None,
    radius_km: float = CENTER_RADIUS_KM,
) -> str | None:
    """Classify a point as ``"center"`` or ``"periphery"`` by Duomo distance.

    Returns None when the coordinate is missing/invalid so callers can exclude
    it rather than mislabel it.
    """
    distance = distance_to_duomo_km(lat, lon)
    if distance is None:
        return None
    return "center" if distance <= radius_km else "periphery"


def assign_neighbourhood(lat: float | None, lon: float | None) -> str | None:
    """Name the popular quartiere a point falls in, else ``"other"``.

    Picks the nearest anchor whose radius contains the point; returns None for
    an invalid coordinate.
    """
    coord = _valid_coord(lat, lon)
    if coord is None:
        return None

    best_name = "other"
    best_distance = math.inf
    for hood in POPULAR_NEIGHBOURHOODS:
        distance_m = haversine_distance_m(coord[0], coord[1], hood.lat, hood.lon)
        if distance_m <= hood.radius_m and distance_m < best_distance:
            best_distance = distance_m
            best_name = hood.name
    return best_name


def is_sparse(review_count: int | float | None) -> bool:
    """True when a venue has fewer than the sparse threshold of reviews.

    A null review count is **not** treated as 0; it is "unknown" and reported
    as non-sparse so it does not inflate the sparse bucket.
    """
    if review_count is None:
        return False
    try:
        count = float(review_count)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(count):
        return False
    return count < SPARSE_REVIEW_THRESHOLD
