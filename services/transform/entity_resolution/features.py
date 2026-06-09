from __future__ import annotations

from typing import Any

from rapidfuzz import fuzz

from .blocking import coordinates, haversine_distance_m
from .preprocess import normalize_name


def _source_name(doc: dict[str, Any]) -> Any:
    return doc.get("restaurant_name") or doc.get("name")


def _similarity(left: Any, right: Any) -> float:
    left_norm = normalize_name(left)
    right_norm = normalize_name(right)
    if not left_norm or not right_norm:
        return 0.0
    return float(fuzz.token_set_ratio(left_norm, right_norm)) / 100.0


def _exact_match(left: Any, right: Any) -> float:
    if left is None or right is None:
        return 0.0
    left_text = str(left).strip()
    right_text = str(right).strip()
    if not left_text or not right_text:
        return 0.0
    return 1.0 if left_text == right_text else 0.0


def _cuisine_tokens(value: Any) -> set[str]:
    if value is None:
        return set()
    values = value if isinstance(value, list) else [value]
    tokens: set[str] = set()
    for item in values:
        tokens.update(normalize_name(item).split())
    return tokens


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def compute_features(
    google_doc: dict[str, Any],
    source_doc: dict[str, Any],
    source: str,
) -> dict[str, float | None]:
    """Compute auditable comparison components for one candidate pair."""
    google_coords = coordinates(google_doc)
    source_coords = coordinates(source_doc)
    geo_dist_m: float | None = None
    if google_coords is not None and source_coords is not None:
        geo_dist_m = haversine_distance_m(
            google_coords[0],
            google_coords[1],
            source_coords[0],
            source_coords[1],
        )
    geo_score = 0.0 if geo_dist_m is None else 1 - min(geo_dist_m, 500.0) / 500.0

    return {
        "name_sim": _similarity(google_doc.get("name"), _source_name(source_doc)),
        "geo_dist_m": geo_dist_m,
        "geo_score": geo_score,
        "street_sim": _similarity(google_doc.get("street"), source_doc.get("street")),
        "phone_match": _exact_match(google_doc.get("phone"), source_doc.get("phone")),
        "website_match": _exact_match(google_doc.get("website"), source_doc.get("website")),
        "postal_code_match": _exact_match(
            google_doc.get("postal_code"), source_doc.get("postal_code")
        ),
        "cuisine_jaccard": _jaccard(
            _cuisine_tokens(google_doc.get("cuisines")),
            _cuisine_tokens(source_doc.get("cuisines")),
        ),
    }
