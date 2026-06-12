from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from extract.google_places_api.config import _default_neighbourhoods

# --- Geographic reference -------------------------------------------------

# Piazza del Duomo — the city-centre anchor for the center/periphery cut.
DUOMO_LAT = 45.4642
DUOMO_LON = 9.1900

# Restaurants within this distance of the Duomo are "center", else "periphery".
# Single, documented, tunable constant (Q7 primary cut).
CENTER_RADIUS_KM = 2.0

# --- Data-quality thresholds ---------------------------------------------

# README §4 reliability convention: below this review count ratings are sparse
# evidence. Used by Q4 (sparse inflation) and Q6 (popularity bins).
SPARSE_REVIEW_THRESHOLD = 20

# Cross-platform agreement tolerance bands on the 0-5 scale (Q1).
TOLERANCE_BANDS_5 = (0.5, 1.0)

# Multi-platform filter: disagreement metrics (Q1, Q2, Q5, Q6) only make sense
# for restaurants present on at least two platforms.
MIN_PLATFORMS_FOR_DISAGREEMENT = 2


@dataclass(frozen=True)
class Neighbourhood:
    """A named Milan quartiere with a representative centre and radius (metres)."""

    name: str
    lat: float
    lon: float
    radius_m: float


def _collapse_anchors() -> list[Neighbourhood]:
    """Group the google_places extraction anchors into named quartieri.

    The acquisition config splits some quartieri into multiple anchors
    (``navigli_1/2/3``). We strip the trailing ``_<n>`` suffix, average the
    coordinates per quartiere, and take the largest anchor radius as the
    quartiere radius — a single source of truth shared with Stage 1.
    """
    groups: dict[str, list] = defaultdict(list)
    for anchor in _default_neighbourhoods():
        base = re.sub(r"_\d+$", "", anchor.name)
        groups[base].append(anchor)

    collapsed: list[Neighbourhood] = []
    for name, anchors in groups.items():
        lat = sum(a.lat for a in anchors) / len(anchors)
        lon = sum(a.lon for a in anchors) / len(anchors)
        radius = max(a.outer_radius_m for a in anchors)
        collapsed.append(Neighbourhood(name=name, lat=lat, lon=lon, radius_m=float(radius)))
    return collapsed


# The 8 named quartieri (duomo, navigli, brera, isola, porta_venezia,
# porta_romana, sempione, loreto) reused for Q7's neighbourhood cut.
POPULAR_NEIGHBOURHOODS: list[Neighbourhood] = _collapse_anchors()

# Destination for CSV + LaTeX exports consumed by the final report.
REPORT_TABLES_DIRNAME = "report/final/tables"
