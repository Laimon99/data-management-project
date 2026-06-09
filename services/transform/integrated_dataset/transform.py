"""Mongo I/O and mapping rules for the final integrated restaurant dataset."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from pymongo import ReplaceOne
from pymongo.errors import PyMongoError

from transform.entity_resolution.scoring import MATCH

from .config import IntegratedSettings

Writer = Callable[[Any, list[dict[str, Any]]], int]

SOURCE_ALL = "all"
SOURCE_TRIPADVISOR = "tripadvisor"
SOURCE_THEFORK = "thefork"
SOURCES = (SOURCE_TRIPADVISOR, SOURCE_THEFORK)

GOOGLE_PROJECTION = {
    "_id": 1,
    "place_id": 1,
    "name": 1,
    "address": 1,
    "street": 1,
    "house_number": 1,
    "postal_code": 1,
    "city": 1,
    "latitude": 1,
    "longitude": 1,
    "rating": 1,
    "review_count": 1,
    "low_review": 1,
    "flags": 1,
    "phone": 1,
    "website": 1,
    "price_level": 1,
    "price_range": 1,
    "photo_count": 1,
    "reviews": 1,
    "cuisines": 1,
    "is_dining": 1,
    "is_operational": 1,
}

SOURCE_PROJECTION = {
    "_id": 1,
    "source_id": 1,
    "ta_location_id": 1,
    "tf_id": 1,
    "restaurant_url": 1,
    "restaurant_name": 1,
    "address": 1,
    "street": 1,
    "house_number": 1,
    "postal_code": 1,
    "city": 1,
    "latitude": 1,
    "longitude": 1,
    "rating": 1,
    "total_review": 1,
    "review_count": 1,
    "low_review": 1,
    "flags": 1,
    "phone": 1,
    "website": 1,
    "email": 1,
    "price_band": 1,
    "price_tier_level": 1,
    "avg_price_eur": 1,
    "discount_pct": 1,
    "photo_count": 1,
    "opening_hours": 1,
    "reviews": 1,
    "cuisines": 1,
    "dietary_options": 1,
}


@dataclass
class BuildReport:
    dry_run: bool = False
    replace_destination: bool = False
    source: str = SOURCE_ALL
    candidates_read: int = 0
    match_candidates: int = 0
    links_selected: int = 0
    link_counts: dict[str, int] = field(default_factory=dict)
    conflict_candidates_skipped: int = 0
    links_deleted: int = 0
    links_written: int = 0
    google_read: int = 0
    integrated_written: int = 0
    integrated_stale_deleted: int = 0
    integrated_with_tripadvisor: int = 0
    integrated_with_thefork: int = 0
    integrated_with_all_three: int = 0


def _selected_sources(source: str) -> tuple[str, ...]:
    if source == SOURCE_ALL:
        return SOURCES
    if source in SOURCES:
        return (source,)
    raise ValueError("source must be one of: tripadvisor, thefork, all")


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _effective_label(candidate: dict[str, Any]) -> str | None:
    llm_label = candidate.get("llm_label")
    return llm_label if not _is_blank(llm_label) else candidate.get("label")


def _candidate_distance(candidate: dict[str, Any]) -> float | None:
    components = candidate.get("components") or {}
    value = components.get("geo_dist_m")
    return float(value) if value is not None else None


def _candidate_name_sim(candidate: dict[str, Any]) -> float:
    return float((candidate.get("components") or {}).get("name_sim") or 0.0)


def _candidate_priority(candidate: dict[str, Any]) -> tuple[int, float, int, float, float, str]:
    llm_priority = 1 if candidate.get("llm_label") == MATCH else 0
    score = float(candidate.get("score") or -1.0)
    fast_path_priority = 1 if candidate.get("fast_path") in {"phone", "website"} else 0
    distance = _candidate_distance(candidate)
    distance_sort = -distance if distance is not None else -1_000_000_000.0
    return (
        llm_priority,
        score,
        fast_path_priority,
        distance_sort,
        _candidate_name_sim(candidate),
        str(candidate.get("_id")),
    )


def _source_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("source_id"))


def _google_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("google_id"))


def _match_method(candidate: dict[str, Any]) -> str:
    if candidate.get("llm_label") == MATCH:
        return "llm"
    if candidate.get("fast_path"):
        return f"deterministic_fast_path_{candidate['fast_path']}"
    return "deterministic_score"


def _match_confidence(candidate: dict[str, Any]) -> float | None:
    if candidate.get("llm_label") == MATCH and candidate.get("llm_confidence") is not None:
        return float(candidate["llm_confidence"])
    return float(candidate["score"]) if candidate.get("score") is not None else None


def _link_doc(
    candidate: dict[str, Any],
    *,
    google_match_counts: Counter[str],
    source_match_counts: Counter[str],
) -> dict[str, Any]:
    source = str(candidate["source"])
    google_id = _google_id(candidate)
    source_id = _source_id(candidate)
    flags: list[str] = []
    if candidate.get("llm_label") == MATCH:
        flags.append("llm_override")
    if google_match_counts[google_id] > 1:
        flags.append(f"multiple_{source}_matches")
    if source_match_counts[source_id] > 1:
        flags.append("source_record_matched_multiple_google")
    if candidate.get("is_chain") is True:
        flags.append("chain_candidate")
    flags.extend(str(item) for item in candidate.get("chain_hardening") or [])

    return {
        "_id": f"{source}:{google_id}:{source_id}",
        "candidate_id": candidate.get("_id"),
        "google_id": google_id,
        "source": source,
        "source_id": source_id,
        "effective_label": MATCH,
        "label": candidate.get("label"),
        "llm_label": candidate.get("llm_label"),
        "score": candidate.get("score"),
        "dmin": candidate.get("dmin"),
        "dmax": candidate.get("dmax"),
        "block_source": candidate.get("block_source"),
        "fast_path": candidate.get("fast_path"),
        "components": dict(candidate.get("components") or {}),
        "is_chain": candidate.get("is_chain") is True,
        "chain_brand": candidate.get("chain_brand"),
        "match_method": _match_method(candidate),
        "match_confidence": _match_confidence(candidate),
        "integration_flags": sorted(set(flags)),
        "_created_at": datetime.now(UTC),
    }


def select_links(
    candidates: list[dict[str, Any]],
    source: str = SOURCE_ALL,
) -> list[dict[str, Any]]:
    selected_sources = _selected_sources(source)
    links: list[dict[str, Any]] = []
    for source_name in selected_sources:
        source_candidates = [
            candidate
            for candidate in candidates
            if candidate.get("source") == source_name and _effective_label(candidate) == MATCH
        ]
        google_counts = Counter(_google_id(candidate) for candidate in source_candidates)
        source_counts = Counter(_source_id(candidate) for candidate in source_candidates)
        used_google: set[str] = set()
        used_source: set[str] = set()
        for candidate in sorted(source_candidates, key=_candidate_priority, reverse=True):
            google_id = _google_id(candidate)
            source_id = _source_id(candidate)
            if google_id in used_google or source_id in used_source:
                continue
            links.append(
                _link_doc(
                    candidate,
                    google_match_counts=google_counts,
                    source_match_counts=source_counts,
                )
            )
            used_google.add(google_id)
            used_source.add(source_id)
    return links


def _bulk_replace(collection: Any, docs: list[dict[str, Any]]) -> int:
    if not docs:
        return 0
    ops = [ReplaceOne({"_id": doc["_id"]}, doc, upsert=True) for doc in docs]
    result = collection.bulk_write(ops, ordered=False)
    return int(result.upserted_count + result.modified_count)


def _serial_replace(collection: Any, docs: list[dict[str, Any]]) -> int:
    written = 0
    for doc in docs:
        result = collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        if result.upserted_id is not None or result.modified_count:
            written += 1
    return written


def _find_source_doc(
    tripadvisor_collection: Any,
    thefork_collection: Any,
    source: str,
    source_id: str | None,
) -> dict[str, Any] | None:
    if not source_id:
        return None
    if source == SOURCE_TRIPADVISOR:
        return tripadvisor_collection.find_one(
            {"ta_location_id": source_id}, SOURCE_PROJECTION
        ) or tripadvisor_collection.find_one({"_id": source_id}, SOURCE_PROJECTION)
    return thefork_collection.find_one(
        {"tf_id": source_id}, SOURCE_PROJECTION
    ) or thefork_collection.find_one({"_id": source_id}, SOURCE_PROJECTION)


def _flags(doc: dict[str, Any] | None) -> list[str]:
    if not doc:
        return []
    value = doc.get("flags")
    return list(value) if isinstance(value, list) else []


def _rating(value: Any) -> float | None:
    return float(value) if value is not None else None


def _review_count(doc: dict[str, Any] | None, source: str) -> int | None:
    if not doc:
        return None
    field = "total_review" if source == SOURCE_TRIPADVISOR else "review_count"
    value = doc.get(field)
    return int(value) if value is not None else None


def _source_url(doc: dict[str, Any] | None) -> str | None:
    if not doc:
        return None
    value = doc.get("_id")
    return str(value) if isinstance(value, str) and value.startswith("http") else None


def _list_union(*values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        items = value if isinstance(value, list) else ([] if value is None else [value])
        for item in items:
            text = str(item).strip()
            key = text.casefold()
            if text and key not in seen:
                result.append(text)
                seen.add(key)
    return result


def _rating_stats(*ratings: float | None) -> tuple[int, float | None, float | None]:
    present = [rating for rating in ratings if rating is not None]
    if not present:
        return 0, None, None
    return len(present), mean(present), max(present) - min(present)


def _link_summary(link: dict[str, Any] | None) -> dict[str, Any] | None:
    if not link:
        return None
    return {
        "candidate_id": link.get("candidate_id"),
        "source_id": link.get("source_id"),
        "score": link.get("score"),
        "match_confidence": link.get("match_confidence"),
        "match_method": link.get("match_method"),
        "block_source": link.get("block_source"),
        "fast_path": link.get("fast_path"),
        "components": link.get("components") or {},
        "integration_flags": link.get("integration_flags") or [],
    }


def integrated_doc(
    google: dict[str, Any],
    *,
    tripadvisor_doc: dict[str, Any] | None,
    thefork_doc: dict[str, Any] | None,
    tripadvisor_link: dict[str, Any] | None,
    thefork_link: dict[str, Any] | None,
) -> dict[str, Any]:
    google_id = str(google.get("place_id") or google.get("_id"))
    google_rating = _rating(google.get("rating"))
    tripadvisor_rating = _rating((tripadvisor_doc or {}).get("rating"))
    thefork_rating_raw = _rating((thefork_doc or {}).get("rating"))
    thefork_rating_5 = thefork_rating_raw / 2 if thefork_rating_raw is not None else None
    rating_count, rating_avg, rating_range = _rating_stats(
        google_rating,
        tripadvisor_rating,
        thefork_rating_5,
    )
    has_tripadvisor = tripadvisor_doc is not None
    has_thefork = thefork_doc is not None
    integration_flags = _list_union(
        (tripadvisor_link or {}).get("integration_flags"),
        (thefork_link or {}).get("integration_flags"),
    )
    platform_count = 1 + int(has_tripadvisor) + int(has_thefork)

    return {
        "_id": google_id,
        "restaurant_id": google_id,
        "integrated_restaurant_id": google_id,
        "canonical_name": google.get("name"),
        "canonical_address": google.get("address"),
        "canonical_street": google.get("street"),
        "canonical_house_number": google.get("house_number"),
        "canonical_postal_code": google.get("postal_code"),
        "canonical_city": google.get("city"),
        "latitude": google.get("latitude"),
        "longitude": google.get("longitude"),
        "coordinate_source": "google"
        if google.get("latitude") is not None and google.get("longitude") is not None
        else "none",
        "google_place_id": google_id,
        "tripadvisor_location_id": (tripadvisor_doc or {}).get("ta_location_id"),
        "tripadvisor_source_url": _source_url(tripadvisor_doc),
        "thefork_id": (thefork_doc or {}).get("tf_id"),
        "thefork_source_id": (thefork_doc or {}).get("source_id"),
        "thefork_restaurant_url": (thefork_doc or {}).get("restaurant_url"),
        "match_status": "match" if has_tripadvisor or has_thefork else "no_match",
        "match_flags": integration_flags,
        "google_rating_raw_5": google_rating,
        "tripadvisor_rating_raw_5": tripadvisor_rating,
        "thefork_rating_raw_10": thefork_rating_raw,
        "google_rating_5": google_rating,
        "tripadvisor_rating_5": tripadvisor_rating,
        "thefork_rating_5": thefork_rating_5,
        "google_review_count": google.get("review_count"),
        "tripadvisor_review_count": _review_count(tripadvisor_doc, SOURCE_TRIPADVISOR),
        "thefork_review_count": _review_count(thefork_doc, SOURCE_THEFORK),
        "rating_platform_count": rating_count,
        "rating_avg_5": rating_avg,
        "rating_range_5": rating_range,
        "google_low_review": google.get("low_review"),
        "tripadvisor_low_review": (tripadvisor_doc or {}).get("low_review"),
        "thefork_low_review": (thefork_doc or {}).get("low_review"),
        "google_flags": _flags(google),
        "tripadvisor_flags": _flags(tripadvisor_doc),
        "thefork_flags": _flags(thefork_doc),
        "integration_flags": integration_flags,
        "has_google": True,
        "has_tripadvisor": has_tripadvisor,
        "has_thefork": has_thefork,
        "platform_count": platform_count,
        "has_all_three_platforms": platform_count == 3,
        "match_provenance": {
            "tripadvisor": _link_summary(tripadvisor_link),
            "thefork": _link_summary(thefork_link),
        },
        "websites": {
            "google": google.get("website"),
            "tripadvisor": (tripadvisor_doc or {}).get("website"),
        },
        "phones": {
            "google": google.get("phone"),
            "tripadvisor": (tripadvisor_doc or {}).get("phone"),
        },
        "emails": {"tripadvisor": (tripadvisor_doc or {}).get("email")},
        "cuisines": _list_union(
            google.get("cuisines"),
            (tripadvisor_doc or {}).get("cuisines"),
            (thefork_doc or {}).get("cuisines"),
        ),
        "dietary_options": _list_union((thefork_doc or {}).get("dietary_options")),
        "price_evidence": {
            "google_price_level": google.get("price_level"),
            "google_price_range": google.get("price_range"),
            "tripadvisor_price_band": (tripadvisor_doc or {}).get("price_band"),
            "tripadvisor_price_tier_level": (tripadvisor_doc or {}).get("price_tier_level"),
            "thefork_avg_price_eur": (thefork_doc or {}).get("avg_price_eur"),
            "thefork_discount_pct": (thefork_doc or {}).get("discount_pct"),
        },
        "opening_hours": {
            "tripadvisor": (tripadvisor_doc or {}).get("opening_hours"),
            "thefork": (thefork_doc or {}).get("opening_hours"),
        },
        "photo_counts": {
            "google": google.get("photo_count"),
            "tripadvisor": (tripadvisor_doc or {}).get("photo_count"),
            "thefork": (thefork_doc or {}).get("photo_count"),
        },
        "review_samples": {
            "google": google.get("reviews") or [],
            "tripadvisor": (tripadvisor_doc or {}).get("reviews") or [],
            "thefork": (thefork_doc or {}).get("reviews") or [],
        },
        "_integrated_at": datetime.now(UTC),
    }


def _links_by_google(links: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    by_google: dict[str, dict[str, dict[str, Any]]] = {}
    for link in links:
        by_google.setdefault(str(link["google_id"]), {})[str(link["source"])] = link
    return by_google


def build_integrated_docs(
    google_docs: list[dict[str, Any]],
    links: list[dict[str, Any]],
    tripadvisor_collection: Any,
    thefork_collection: Any,
) -> list[dict[str, Any]]:
    link_map = _links_by_google(links)
    docs: list[dict[str, Any]] = []
    for google in google_docs:
        google_id = str(google.get("place_id") or google.get("_id"))
        source_links = link_map.get(google_id, {})
        tripadvisor_link = source_links.get(SOURCE_TRIPADVISOR)
        thefork_link = source_links.get(SOURCE_THEFORK)
        tripadvisor_doc = (
            _find_source_doc(
                tripadvisor_collection,
                thefork_collection,
                SOURCE_TRIPADVISOR,
                tripadvisor_link.get("source_id"),
            )
            if tripadvisor_link
            else None
        )
        thefork_doc = (
            _find_source_doc(
                tripadvisor_collection,
                thefork_collection,
                SOURCE_THEFORK,
                thefork_link.get("source_id"),
            )
            if thefork_link
            else None
        )
        docs.append(
            integrated_doc(
                google,
                tripadvisor_doc=tripadvisor_doc,
                thefork_doc=thefork_doc,
                tripadvisor_link=tripadvisor_link,
                thefork_link=thefork_link,
            )
        )
    return docs


def _replace_batches(
    collection: Any,
    docs: list[dict[str, Any]],
    batch_size: int,
    writer: Writer = _bulk_replace,
) -> int:
    written = 0
    for start in range(0, len(docs), batch_size):
        batch = docs[start : start + batch_size]
        try:
            written += writer(collection, batch)
        except NotImplementedError:
            written += _serial_replace(collection, batch)
    return written


def build_collections(
    google_collection: Any,
    tripadvisor_collection: Any,
    thefork_collection: Any,
    candidates_collection: Any,
    links_collection: Any,
    integrated_collection: Any,
    settings: IntegratedSettings,
    *,
    source: str = SOURCE_ALL,
    dry_run: bool = False,
    replace_destination: bool = False,
    writer: Writer = _bulk_replace,
) -> BuildReport:
    selected_sources = _selected_sources(source)
    report = BuildReport(dry_run=dry_run, replace_destination=replace_destination, source=source)

    candidate_docs = list(candidates_collection.find({"source": {"$in": list(selected_sources)}}))
    report.candidates_read = len(candidate_docs)
    report.match_candidates = sum(1 for doc in candidate_docs if _effective_label(doc) == MATCH)
    selected_links = select_links(candidate_docs, source)
    report.links_selected = len(selected_links)
    report.link_counts = dict(Counter(str(link["source"]) for link in selected_links))
    report.conflict_candidates_skipped = max(report.match_candidates - len(selected_links), 0)

    if not dry_run:
        if replace_destination:
            report.links_deleted = int(
                links_collection.delete_many(
                    {"source": {"$in": list(selected_sources)}}
                ).deleted_count
            )
        report.links_written = _replace_batches(
            links_collection,
            selected_links,
            settings.batch_size,
            writer,
        )

    if dry_run:
        untouched_sources = [item for item in SOURCES if item not in selected_sources]
        all_links = selected_links + list(
            links_collection.find({"source": {"$in": untouched_sources}})
        )
    else:
        all_links = list(links_collection.find({"source": {"$in": list(SOURCES)}}))
    google_docs = list(
        google_collection.find({"is_dining": True, "is_operational": True}, GOOGLE_PROJECTION)
    )
    report.google_read = len(google_docs)
    integrated_docs = build_integrated_docs(
        google_docs,
        all_links,
        tripadvisor_collection,
        thefork_collection,
    )
    report.integrated_with_tripadvisor = sum(1 for doc in integrated_docs if doc["has_tripadvisor"])
    report.integrated_with_thefork = sum(1 for doc in integrated_docs if doc["has_thefork"])
    report.integrated_with_all_three = sum(
        1 for doc in integrated_docs if doc["has_all_three_platforms"]
    )

    if not dry_run:
        if replace_destination:
            integrated_collection.delete_many({})
        report.integrated_written = _replace_batches(
            integrated_collection,
            integrated_docs,
            settings.batch_size,
            writer,
        )
        seen_ids = [doc["_id"] for doc in integrated_docs]
        report.integrated_stale_deleted = int(
            integrated_collection.delete_many({"_id": {"$nin": seen_ids}}).deleted_count
        )
    return report


def open_integrated_collections(
    settings: IntegratedSettings,
) -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    """Open (client, google, tripadvisor, thefork, candidates, links, integrated)."""
    from pymongo import MongoClient

    client: Any = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except PyMongoError:
        client.close()
        raise
    db = client[settings.mongo_db]
    return (
        client,
        db[settings.google_collection],
        db[settings.tripadvisor_collection],
        db[settings.thefork_collection],
        db[settings.candidates_collection],
        db[settings.links_collection],
        db[settings.integrated_collection],
    )
