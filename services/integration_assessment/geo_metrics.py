from __future__ import annotations

from statistics import median
from typing import Any

from transform.entity_resolution.blocking import coordinates, has_coordinates, haversine_distance_m
from transform.entity_resolution.scoring import MATCH, UNBLOCKABLE

GEOCODING_FIELDNAMES = [
    "candidate_id",
    "google_id",
    "tripadvisor_id",
    "distance_m",
    "stored_candidate_geo_dist_m",
    "stored_link_geo_dist_m",
    "within_50m",
    "within_100m",
    "within_250m",
]


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _keyed_docs(docs: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    keyed: dict[str, dict[str, Any]] = {}
    for doc in docs:
        for key in keys:
            value = doc.get(key)
            if value not in (None, ""):
                keyed.setdefault(str(value), doc)
    return keyed


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * q)
    return ordered[index]


def _pct(count: int, total: int) -> float | None:
    return count / total if total else None


def _link_lookup(links: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for link in links:
        source = str(link.get("source") or "")
        google_id = str(link.get("google_id") or "")
        source_id = str(link.get("source_id") or "")
        if source and google_id and source_id:
            lookup[(source, google_id, source_id)] = link
    return lookup


def compute_geo_metrics(
    gold_rows: list[dict[str, str]],
    candidates: list[dict[str, Any]],
    links: list[dict[str, Any]],
    google_docs: list[dict[str, Any]],
    tripadvisor_docs: list[dict[str, Any]],
    *,
    buckets_m: tuple[int, ...] = (50, 100, 250),
) -> dict[str, Any]:
    """Measure Tripadvisor geocoding distance against confirmed Google matches."""
    google_by_id = _keyed_docs(google_docs, ("place_id", "_id"))
    tripadvisor_by_id = _keyed_docs(tripadvisor_docs, ("ta_location_id", "_id", "source_url"))
    candidates_by_id = _keyed_docs(candidates, ("_id",))
    links_by_pair = _link_lookup(links)

    rows: list[dict[str, Any]] = []
    missing_coordinates = 0
    for row in gold_rows:
        if str(row.get("human_label", "")).upper() != MATCH:
            continue
        if str(row.get("source", "")).lower() != "tripadvisor":
            continue
        google_id = str(row.get("google_id") or "")
        tripadvisor_id = str(row.get("source_id") or "")
        google_doc = google_by_id.get(google_id)
        tripadvisor_doc = tripadvisor_by_id.get(tripadvisor_id)
        google_coords = coordinates(google_doc or {})
        tripadvisor_coords = coordinates(tripadvisor_doc or {})
        if google_coords is None or tripadvisor_coords is None:
            missing_coordinates += 1
            continue

        distance_m = haversine_distance_m(
            google_coords[0],
            google_coords[1],
            tripadvisor_coords[0],
            tripadvisor_coords[1],
        )
        candidate = candidates_by_id.get(row["_id"]) or {}
        link = links_by_pair.get(("tripadvisor", google_id, tripadvisor_id)) or {}
        candidate_dist = _as_float((candidate.get("components") or {}).get("geo_dist_m"))
        link_dist = _as_float((link.get("components") or {}).get("geo_dist_m"))
        rows.append(
            {
                "candidate_id": row["_id"],
                "google_id": google_id,
                "tripadvisor_id": tripadvisor_id,
                "distance_m": distance_m,
                "stored_candidate_geo_dist_m": candidate_dist,
                "stored_link_geo_dist_m": link_dist,
                **{f"within_{bucket}m": distance_m <= bucket for bucket in buckets_m},
            }
        )

    distances = [float(row["distance_m"]) for row in rows]
    coverage_count = sum(1 for doc in tripadvisor_docs if has_coordinates(doc))
    total_tripadvisor = len(tripadvisor_docs)
    unblockable_count = sum(
        1
        for candidate in candidates
        if candidate.get("source") == "tripadvisor" and candidate.get("label") == UNBLOCKABLE
    )
    link_deltas = [
        abs(float(row["distance_m"]) - float(row["stored_link_geo_dist_m"]))
        for row in rows
        if row["stored_link_geo_dist_m"] is not None
    ]

    return {
        "summary": {
            "gold_tripadvisor_matches": sum(
                1
                for row in gold_rows
                if row.get("human_label") == MATCH and row.get("source") == "tripadvisor"
            ),
            "distance_rows": len(rows),
            "missing_coordinate_pairs": missing_coordinates,
            "median_m": median(distances) if distances else None,
            "p90_m": _quantile(distances, 0.90),
            "p95_m": _quantile(distances, 0.95),
            "max_m": max(distances) if distances else None,
            **{
                f"within_{bucket}m_pct": _pct(
                    sum(1 for distance in distances if distance <= bucket),
                    len(distances),
                )
                for bucket in buckets_m
            },
            "tripadvisor_coordinate_coverage_pct": _pct(coverage_count, total_tripadvisor),
            "tripadvisor_with_coordinates": coverage_count,
            "tripadvisor_without_coordinates": total_tripadvisor - coverage_count,
            "tripadvisor_clean_records": total_tripadvisor,
            "tripadvisor_unblockable_candidates": unblockable_count,
            "max_abs_stored_link_delta_m": max(link_deltas) if link_deltas else None,
        },
        "rows": rows,
    }
