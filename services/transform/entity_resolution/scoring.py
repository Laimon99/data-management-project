from __future__ import annotations

from typing import Any

MATCH = "MATCH"
NON_MATCH = "NON_MATCH"
UNCERTAIN = "UNCERTAIN"
UNBLOCKABLE = "UNBLOCKABLE"

TRIPADVISOR_WEIGHTS = {
    "name_sim": 0.40,
    "geo_score": 0.25,
    "street_sim": 0.10,
    "phone_match": 0.15,
    "website_match": 0.10,
}
THEFORK_WEIGHTS = {
    "name_sim": 0.50,
    "geo_score": 0.35,
    "street_sim": 0.15,
}


def score_components(components: dict[str, Any], source: str) -> float:
    """Compute the source-specific composite score."""
    weights = TRIPADVISOR_WEIGHTS if source == "tripadvisor" else THEFORK_WEIGHTS
    return sum(float(components.get(name) or 0.0) * weight for name, weight in weights.items())


def label(score: float, dmin: float, dmax: float) -> str:
    if score >= dmax:
        return MATCH
    if score <= dmin:
        return NON_MATCH
    return UNCERTAIN
