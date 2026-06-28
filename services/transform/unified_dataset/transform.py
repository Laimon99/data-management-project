"""Link selection and integrated-document construction for the final dataset."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from pymongo import ReplaceOne
from pymongo.errors import PyMongoError

from .config import UnifiedSettings
from .cuisine import merge_cuisine

SOURCE_ALL = "all"
SOURCE_TRIPADVISOR = "tripadvisor"
SOURCE_THEFORK = "thefork"
SOURCES = (SOURCE_TRIPADVISOR, SOURCE_THEFORK)
MATCH = "MATCH"

Writer = Callable[[Any, list[dict[str, Any]]], tuple[int, int]]

GOOGLE_AMENITY_FIELDS = (
    "dine_in",
    "takeout",
    "delivery",
    "reservable",
    "curbside_pickup",
    "outdoor_seating",
    "serves_vegetarian_food",
    "serves_breakfast",
    "serves_lunch",
    "serves_dinner",
    "serves_beer",
    "serves_wine",
    "serves_cocktails",
    "serves_coffee",
    "serves_dessert",
    "live_music",
    "good_for_children",
    "good_for_groups",
    "allows_dogs",
    "restroom",
    "menu_for_children",
    "good_for_watching_sports",
)

GOOGLE_PRICE_LEVELS = {
    "PRICE_LEVEL_INEXPENSIVE": "INEXPENSIVE",
    "PRICE_LEVEL_MODERATE": "MODERATE",
    "PRICE_LEVEL_EXPENSIVE": "EXPENSIVE",
    "PRICE_LEVEL_VERY_EXPENSIVE": "VERY_EXPENSIVE",
}

INT_TO_PRICE_LABEL = {
    1: "INEXPENSIVE",
    2: "MODERATE",
    3: "EXPENSIVE",
    4: "VERY_EXPENSIVE",
}


@dataclass
class SourceLinkReport:
    source: str
    match_candidates: int = 0
    selected_links: int = 0
    conflict_links: int = 0
    llm_override_links: int = 0
    rejected_candidates: int = 0
    inserted: int = 0
    modified: int = 0
    stale_deleted: int = 0


@dataclass
class IntegratedReport:
    google_read: int = 0
    written: int = 0
    inserted: int = 0
    modified: int = 0
    stale_deleted: int = 0
    with_tripadvisor: int = 0
    with_thefork: int = 0
    with_all_three: int = 0
    missing_linked_source_docs: int = 0
    cuisine_unmapped: set[str] = field(default_factory=set)


@dataclass
class UnifiedRunReport:
    dry_run: bool
    replace_destination: bool
    skip_links: bool
    links: list[SourceLinkReport] = field(default_factory=list)
    integrated: IntegratedReport = field(default_factory=IntegratedReport)


def bulk_replace(collection: Any, docs: list[dict[str, Any]]) -> tuple[int, int]:
    """Production write path using ReplaceOne upserts."""
    if not docs:
        return 0, 0
    ops = [ReplaceOne({"_id": doc["_id"]}, doc, upsert=True) for doc in docs]
    result = collection.bulk_write(ops, ordered=False)
    return result.upserted_count, result.modified_count


def serial_replace(collection: Any, docs: list[dict[str, Any]]) -> tuple[int, int]:
    """mongomock-compatible writer equivalent to :func:`bulk_replace`."""
    inserted = modified = 0
    for doc in docs:
        result = collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        if result.upserted_id is not None:
            inserted += 1
        else:
            modified += result.modified_count
    return inserted, modified


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _effective_label(candidate: dict[str, Any]) -> str | None:
    llm_label = candidate.get("llm_label")
    if not _is_blank(llm_label):
        return str(llm_label)
    label = candidate.get("label")
    return None if _is_blank(label) else str(label)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _selected_sources(source: str) -> tuple[str, ...]:
    if source == SOURCE_ALL:
        return SOURCES
    if source in SOURCES:
        return (source,)
    raise ValueError(f"source must be one of: {', '.join(SOURCES)}, all")


def _sort_key(candidate: dict[str, Any]) -> tuple[int, float, int, float, float, str]:
    components = candidate.get("components") or {}
    score = _as_float(candidate.get("score"))
    geo_dist_m = _as_float(components.get("geo_dist_m"))
    name_sim = _as_float(components.get("name_sim"))
    return (
        1 if candidate.get("llm_label") == MATCH else 0,
        -1.0 if score is None else score,
        1 if not _is_blank(candidate.get("fast_path")) else 0,
        float("-inf") if geo_dist_m is None else -geo_dist_m,
        -1.0 if name_sim is None else name_sim,
        str(candidate.get("_id", "")),
    )


def _website_host(value: Any) -> str | None:
    if _is_blank(value):
        return None
    text = str(value).strip().lower()
    text = text.removeprefix("https://").removeprefix("http://")
    text = text.removeprefix("www.")
    host = text.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    return host.rstrip(".") or None


def _contact_evidence(
    google_doc: dict[str, Any],
    tripadvisor_doc: dict[str, Any] | None,
) -> dict[str, Any]:
    google_website = google_doc.get("website")
    tripadvisor_website = tripadvisor_doc.get("website") if tripadvisor_doc else None
    website_evidence = [
        {"source": source, "value": value}
        for source, value in (
            ("google", google_website),
            ("tripadvisor", tripadvisor_website),
        )
        if not _is_blank(value)
    ]

    website = None
    website_source = None
    website_match_status = "missing"
    if google_website and tripadvisor_website:
        google_host = _website_host(google_website)
        tripadvisor_host = _website_host(tripadvisor_website)
        if google_website == tripadvisor_website:
            website = google_website
            website_source = "google_tripadvisor"
            website_match_status = "exact_match"
        elif google_host is not None and google_host == tripadvisor_host:
            website = google_host
            website_source = "google_tripadvisor"
            website_match_status = "host_match"
        else:
            website = google_website
            website_source = "google"
            website_match_status = "conflict"
    elif google_website:
        website = google_website
        website_source = "google"
        website_match_status = "single_source"
    elif tripadvisor_website:
        website = tripadvisor_website
        website_source = "tripadvisor"
        website_match_status = "single_source"

    google_phone = google_doc.get("phone")
    tripadvisor_phone = tripadvisor_doc.get("phone") if tripadvisor_doc else None
    phone_evidence = [
        {"source": source, "value": value}
        for source, value in (
            ("google", google_phone),
            ("tripadvisor", tripadvisor_phone),
        )
        if not _is_blank(value)
    ]
    phones = []
    for evidence in phone_evidence:
        if evidence["value"] not in phones:
            phones.append(evidence["value"])

    phone_match_status = "missing"
    if google_phone and tripadvisor_phone:
        if google_phone == tripadvisor_phone:
            phone_match_status = "exact_match"
        else:
            phone_match_status = "conflict"
    elif google_phone:
        phone_match_status = "single_source"
    elif tripadvisor_phone:
        phone_match_status = "single_source"

    return {
        "website": website,
        "website_source": website_source,
        "website_match_status": website_match_status,
        "website_evidence": website_evidence,
        "phone_match_status": phone_match_status,
        "phones": phones,
        "phone_evidence": phone_evidence,
    }


def _thefork_price_level(avg_price_eur: Any) -> str | None:
    value = _as_float(avg_price_eur)
    if value is None:
        return None
    if value <= 20:
        return "INEXPENSIVE"
    if value <= 40:
        return "MODERATE"
    if value <= 70:
        return "EXPENSIVE"
    return "VERY_EXPENSIVE"


def _price_evidence(
    google_doc: dict[str, Any],
    tripadvisor_doc: dict[str, Any] | None,
    thefork_doc: dict[str, Any] | None,
) -> dict[str, Any]:
    google_raw = google_doc.get("price_level")
    google_level = GOOGLE_PRICE_LEVELS.get(str(google_raw)) if not _is_blank(google_raw) else None
    tripadvisor_raw = tripadvisor_doc.get("price_tier_level") if tripadvisor_doc else None
    tripadvisor_level = (
        INT_TO_PRICE_LABEL.get(int(tripadvisor_raw)) if isinstance(tripadvisor_raw, int) else None
    )
    thefork_raw = thefork_doc.get("avg_price_eur") if thefork_doc else None
    thefork_level = _thefork_price_level(thefork_raw)

    evidence = [
        {"source": "google", "level": google_level, "raw": google_raw},
        {"source": "tripadvisor", "level": tripadvisor_level, "raw": tripadvisor_raw},
        {"source": "thefork", "level": thefork_level, "raw": thefork_raw},
    ]
    evidence = [item for item in evidence if item["level"] is not None]

    if not evidence:
        return {"price_level": None, "price_level_source": None, "price_evidence": []}

    counts: dict[str, list[str]] = {}
    for item in evidence:
        label = item["level"]
        counts.setdefault(label, []).append(item["source"])

    max_count = max(len(v) for v in counts.values())
    winners = sorted(label for label, srcs in counts.items() if len(srcs) == max_count)

    if len(winners) == 1:
        winner_sources = counts[winners[0]]
        source_label = winner_sources[0] if len(winner_sources) == 1 else "majority"
        return {
            "price_level": winners[0],
            "price_level_source": source_label,
            "price_evidence": evidence,
        }

    return {
        "price_level": winners,
        "price_level_source": "tie",
        "price_evidence": evidence,
    }


def _source_conflict_flag(source: str) -> str:
    return f"multiple_{source}_matches"


def _match_confidence(candidate: dict[str, Any]) -> float | None:
    llm_label = candidate.get("llm_label")
    if not _is_blank(llm_label) and candidate.get("llm_confidence") is not None:
        return _as_float(candidate.get("llm_confidence"))
    return _as_float(candidate.get("score"))


def _link_doc(
    candidate: dict[str, Any],
    *,
    flags: list[str],
    rejected_candidate_ids: list[str],
    now: datetime,
) -> dict[str, Any]:
    source = str(candidate["source"])
    google_id = str(candidate["google_id"])
    source_id = str(candidate["source_id"])
    effective_label = _effective_label(candidate)
    llm_label = candidate.get("llm_label")
    label = candidate.get("label")
    method = "llm" if not _is_blank(llm_label) else "automatic"

    return {
        "_id": f"{source}:{google_id}:{source_id}",
        "candidate_id": candidate["_id"],
        "google_id": google_id,
        "source": source,
        "source_id": source_id,
        "effective_label": effective_label,
        "label": label,
        "llm_label": llm_label,
        "match_method": method,
        "match_confidence": _match_confidence(candidate),
        "score": candidate.get("score"),
        "dmin": candidate.get("dmin"),
        "dmax": candidate.get("dmax"),
        "block_source": candidate.get("block_source"),
        "fast_path": candidate.get("fast_path"),
        "is_chain": candidate.get("is_chain", False),
        "chain_brand": candidate.get("chain_brand"),
        "chain_hardening": candidate.get("chain_hardening", []),
        "components": candidate.get("components", {}),
        "flags": sorted(set(flags)),
        "rejected_candidate_ids": sorted(set(rejected_candidate_ids)),
        "_updated_at": now,
    }


def select_links_for_source(
    candidates: Iterable[dict[str, Any]],
    source: str,
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], SourceLinkReport]:
    """Select one-to-one MATCH links for one non-Google source."""
    now = now or datetime.now(UTC)
    report = SourceLinkReport(source=source)
    match_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("source") == source
        and not _is_blank(candidate.get("google_id"))
        and not _is_blank(candidate.get("source_id"))
        and _effective_label(candidate) == MATCH
    ]
    report.match_candidates = len(match_candidates)

    by_google: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_candidate_id: dict[str, dict[str, Any]] = {}
    for candidate in match_candidates:
        by_google[str(candidate["google_id"])].append(candidate)
        by_source[str(candidate["source_id"])].append(candidate)
        by_candidate_id[str(candidate["_id"])] = candidate

    used_google: set[str] = set()
    used_source: set[str] = set()
    selected: list[dict[str, Any]] = []
    rejected_by_selected: dict[str, set[str]] = defaultdict(set)

    for candidate in sorted(match_candidates, key=_sort_key, reverse=True):
        google_id = str(candidate["google_id"])
        source_id = str(candidate["source_id"])
        if google_id in used_google or source_id in used_source:
            selected_candidates = [
                selected_candidate
                for selected_candidate in selected
                if selected_candidate["google_id"] == google_id
                or selected_candidate["source_id"] == source_id
            ]
            for selected_candidate in selected_candidates:
                rejected_by_selected[str(selected_candidate["_id"])].add(str(candidate["_id"]))
            continue
        selected.append(candidate)
        used_google.add(google_id)
        used_source.add(source_id)

    links: list[dict[str, Any]] = []
    for candidate in selected:
        google_id = str(candidate["google_id"])
        source_id = str(candidate["source_id"])
        candidate_id = str(candidate["_id"])
        flags: list[str] = []
        rejected_ids = set(rejected_by_selected.get(candidate_id, set()))

        google_competitors = [c for c in by_google[google_id] if c["_id"] != candidate["_id"]]
        source_competitors = [c for c in by_source[source_id] if c["_id"] != candidate["_id"]]
        if google_competitors:
            flags.append(_source_conflict_flag(source))
            rejected_ids.update(str(c["_id"]) for c in google_competitors)
        if source_competitors:
            flags.append("source_record_matched_multiple_google")
            rejected_ids.update(str(c["_id"]) for c in source_competitors)
        if candidate.get("llm_label") == MATCH and candidate.get("label") != MATCH:
            flags.append("llm_override")
            report.llm_override_links += 1

        link = _link_doc(
            candidate,
            flags=flags,
            rejected_candidate_ids=[cid for cid in rejected_ids if cid in by_candidate_id],
            now=now,
        )
        if flags:
            report.conflict_links += 1
        report.rejected_candidates += len(link["rejected_candidate_ids"])
        links.append(link)

    report.selected_links = len(links)
    return links, report


def select_links(
    candidates_collection: Any,
    source: str = SOURCE_ALL,
) -> tuple[list[dict[str, Any]], list[SourceLinkReport]]:
    """Select links for Tripadvisor and TheFork from the candidate collection."""
    selected_sources = _selected_sources(source)
    candidates = list(
        candidates_collection.find(
            {
                "source": {"$in": list(selected_sources)},
                "$or": [{"label": MATCH}, {"llm_label": MATCH}],
                "llm_label": {"$ne": "NON_MATCH"},
            }
        )
    )
    links: list[dict[str, Any]] = []
    reports: list[SourceLinkReport] = []
    now = datetime.now(UTC)
    for src in selected_sources:
        source_links, source_report = select_links_for_source(candidates, src, now=now)
        links.extend(source_links)
        reports.append(source_report)
    return links, reports


def _flush_batches(
    collection: Any,
    docs: list[dict[str, Any]],
    settings: UnifiedSettings,
    writer: Writer,
) -> tuple[int, int]:
    inserted = modified = 0
    for start in range(0, len(docs), settings.batch_size):
        batch = docs[start : start + settings.batch_size]
        batch_inserted, batch_modified = writer(collection, batch)
        inserted += batch_inserted
        modified += batch_modified
    return inserted, modified


def _replace_collection_contents(
    collection: Any,
    docs: list[dict[str, Any]],
    settings: UnifiedSettings,
    writer: Writer,
) -> tuple[int, int, int]:
    collection.delete_many({})
    inserted, modified = _flush_batches(collection, docs, settings, writer)
    return inserted, modified, 0


def _upsert_and_delete_stale(
    collection: Any,
    docs: list[dict[str, Any]],
    settings: UnifiedSettings,
    writer: Writer,
) -> tuple[int, int, int]:
    inserted, modified = _flush_batches(collection, docs, settings, writer)
    ids = [doc["_id"] for doc in docs]
    result = collection.delete_many({"_id": {"$nin": ids}})
    return inserted, modified, int(result.deleted_count)


def _upsert_links_for_source(
    collection: Any,
    docs: list[dict[str, Any]],
    source: str,
    settings: UnifiedSettings,
    writer: Writer,
    *,
    replace: bool,
) -> tuple[int, int, int]:
    if replace:
        stale_deleted = int(collection.delete_many({"source": source}).deleted_count)
    else:
        ids = [doc["_id"] for doc in docs]
        stale_deleted = int(
            collection.delete_many({"source": source, "_id": {"$nin": ids}}).deleted_count
        )
    inserted, modified = _flush_batches(collection, docs, settings, writer)
    return inserted, modified, stale_deleted


def _keyed_docs(collection: Any, keys: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for doc in collection.find():
        for key in keys:
            value = doc.get(key)
            if not _is_blank(value):
                mapping[str(value)] = doc
    return mapping


def _clean_obj(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def _copy_fields(doc: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: doc[field] for field in fields if field in doc and doc[field] is not None}


def _google_source_block(doc: dict[str, Any]) -> dict[str, Any]:
    return _clean_obj(
        {
            "ids": _clean_obj({"_id": doc.get("_id"), "place_id": doc.get("place_id")}),
            "name": doc.get("name"),
            "address": _copy_fields(
                doc,
                (
                    "address",
                    "street",
                    "house_number",
                    "postal_code",
                    "locality",
                    "province",
                    "country",
                    "city",
                ),
            ),
            "coordinates": _clean_obj(
                {
                    "latitude": doc.get("latitude"),
                    "longitude": doc.get("longitude"),
                    "coordinate_source": "google",
                }
            ),
            "rating": _clean_obj({"raw_5": doc.get("rating"), "rating_5": doc.get("rating")}),
            "review_count": doc.get("review_count"),
            "contacts": _copy_fields(doc, ("website", "phone")),
            "price": _copy_fields(doc, ("price_level", "price_range")),
            "classification": _copy_fields(
                doc,
                (
                    "primary_type",
                    "types",
                    "category_tier",
                    "is_dining",
                    "business_status",
                    "is_operational",
                ),
            ),
            "amenities": _copy_fields(doc, GOOGLE_AMENITY_FIELDS),
            "photo_count": doc.get("photo_count"),
            "reviews": doc.get("reviews"),
            "flags": doc.get("flags", []),
        }
    )


def _tripadvisor_source_block(doc: dict[str, Any], link: dict[str, Any]) -> dict[str, Any]:
    return _clean_obj(
        {
            "ids": _clean_obj(
                {
                    "_id": doc.get("_id"),
                    "ta_location_id": doc.get("ta_location_id"),
                    "source_url": doc.get("source_url"),
                }
            ),
            "name": doc.get("restaurant_name"),
            "address": _copy_fields(
                doc,
                ("address", "street", "house_number", "postal_code", "city"),
            ),
            "coordinates": _clean_obj(
                {
                    "latitude": doc.get("latitude"),
                    "longitude": doc.get("longitude"),
                    "has_coordinates": doc.get("has_coordinates"),
                    "coordinate_source": "tripadvisor_geocoded",
                }
            ),
            "rating": _clean_obj({"raw_5": doc.get("rating"), "rating_5": doc.get("rating")}),
            "review_count": doc.get("total_review"),
            "contacts": _copy_fields(doc, ("website", "phone", "email")),
            "price": _copy_fields(doc, ("price_band", "price_tier_level")),
            "cuisines": doc.get("cuisines"),
            "opening_hours": doc.get("opening_hours"),
            "photo_count": doc.get("photo_count"),
            "reviews": doc.get("reviews"),
            "sample_size": doc.get("sample_size"),
            "flags": doc.get("flags", []),
            "match": _match_block(link),
        }
    )


def _thefork_rating_5(doc: dict[str, Any]) -> float | None:
    rating = _as_float(doc.get("rating"))
    return None if rating is None else rating / 2


def _thefork_source_block(doc: dict[str, Any], link: dict[str, Any]) -> dict[str, Any]:
    return _clean_obj(
        {
            "ids": _clean_obj(
                {
                    "_id": doc.get("_id"),
                    "source": doc.get("source"),
                    "source_id": doc.get("source_id"),
                    "tf_id": doc.get("tf_id"),
                    "restaurant_url": doc.get("restaurant_url"),
                }
            ),
            "name": doc.get("restaurant_name"),
            "address": _copy_fields(
                doc,
                ("address", "street", "house_number", "postal_code", "city"),
            ),
            "coordinates": _clean_obj(
                {
                    "latitude": doc.get("latitude"),
                    "longitude": doc.get("longitude"),
                    "coordinate_source": "thefork",
                }
            ),
            "rating": _clean_obj({"raw_10": doc.get("rating"), "rating_5": _thefork_rating_5(doc)}),
            "review_count": doc.get("review_count"),
            "price": _copy_fields(doc, ("avg_price_eur", "discount_pct", "has_discount")),
            "cuisines": doc.get("cuisines"),
            "dietary_options": doc.get("dietary_options"),
            "opening_hours": doc.get("opening_hours"),
            "photo_count": doc.get("photo_count"),
            "review_snippets": doc.get("review_snippets"),
            "reviews": doc.get("reviews"),
            "sample_size": doc.get("sample_size"),
            "sample_avg_rating": doc.get("sample_avg_rating"),
            "rating_sample_divergent": doc.get("rating_sample_divergent"),
            "scrape_provenance": _copy_fields(
                doc,
                ("scraped_at", "source_page_number", "detail_scraped"),
            ),
            "flags": doc.get("flags", []),
            "match": _match_block(link),
        }
    )


def _match_block(link: dict[str, Any]) -> dict[str, Any]:
    return _clean_obj(
        {
            "link_id": link.get("_id"),
            "candidate_id": link.get("candidate_id"),
            "effective_label": link.get("effective_label"),
            "label": link.get("label"),
            "llm_label": link.get("llm_label"),
            "match_method": link.get("match_method"),
            "score": link.get("score"),
            "block_source": link.get("block_source"),
            "fast_path": link.get("fast_path"),
            "components": link.get("components"),
            "flags": link.get("flags", []),
            "rejected_candidate_ids": link.get("rejected_candidate_ids", []),
        }
    )


def _links_by_google(links: Iterable[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    by_google: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for link in links:
        by_google[str(link["google_id"])][str(link["source"])] = link
    return by_google


def _source_ids_for_links(links: Iterable[dict[str, Any]], source: str) -> set[str]:
    return {str(link["source_id"]) for link in links if link.get("source") == source}


def _rating_metrics(ratings: list[float]) -> tuple[int, float | None, float | None]:
    if not ratings:
        return 0, None, None
    return len(ratings), round(mean(ratings), 3), round(max(ratings) - min(ratings), 3)


def _append_link_flags(integration_flags: list[str], link: dict[str, Any] | None) -> None:
    if not link:
        return
    for flag in link.get("flags", []):
        if flag not in integration_flags:
            integration_flags.append(flag)


def build_integrated_docs(
    google_collection: Any,
    tripadvisor_collection: Any,
    thefork_collection: Any,
    links: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], IntegratedReport]:
    """Build Google-seeded integrated documents from clean sources and selected links."""
    now = now or datetime.now(UTC)
    report = IntegratedReport()
    links_lookup = _links_by_google(links)
    tripadvisor_docs = _keyed_docs(tripadvisor_collection, ("ta_location_id", "_id", "source_url"))
    thefork_docs = _keyed_docs(thefork_collection, ("tf_id", "_id", "source_id"))

    docs: list[dict[str, Any]] = []
    for google in google_collection.find({"is_dining": True, "is_operational": True}):
        report.google_read += 1
        google_id = str(google.get("place_id") or google.get("_id"))
        restaurant_id = f"google:{google_id}"
        source_links = links_lookup.get(google_id, {})
        tripadvisor_link = source_links.get(SOURCE_TRIPADVISOR)
        thefork_link = source_links.get(SOURCE_THEFORK)
        ta_doc = None
        tf_doc = None

        sources: dict[str, Any] = {"google": _google_source_block(google)}
        integration_flags: list[str] = []
        tripadvisor_rating = None
        thefork_rating_raw = None
        thefork_rating_5 = None
        tripadvisor_review_count = None
        thefork_review_count = None

        if tripadvisor_link is not None:
            ta_doc = tripadvisor_docs.get(str(tripadvisor_link["source_id"]))
            if ta_doc is None:
                integration_flags.append("missing_tripadvisor_source_doc")
                report.missing_linked_source_docs += 1
            else:
                sources[SOURCE_TRIPADVISOR] = _tripadvisor_source_block(ta_doc, tripadvisor_link)
                tripadvisor_rating = _as_float(ta_doc.get("rating"))
                tripadvisor_review_count = ta_doc.get("total_review")
                report.with_tripadvisor += 1
            _append_link_flags(integration_flags, tripadvisor_link)

        if thefork_link is not None:
            tf_doc = thefork_docs.get(str(thefork_link["source_id"]))
            if tf_doc is None:
                integration_flags.append("missing_thefork_source_doc")
                report.missing_linked_source_docs += 1
            else:
                sources[SOURCE_THEFORK] = _thefork_source_block(tf_doc, thefork_link)
                thefork_rating_raw = _as_float(tf_doc.get("rating"))
                thefork_rating_5 = _thefork_rating_5(tf_doc)
                thefork_review_count = tf_doc.get("review_count")
                report.with_thefork += 1
            _append_link_flags(integration_flags, thefork_link)

        has_tripadvisor = SOURCE_TRIPADVISOR in sources
        has_thefork = SOURCE_THEFORK in sources
        if has_tripadvisor and has_thefork:
            report.with_all_three += 1

        google_rating = _as_float(google.get("rating"))
        ratings = [
            rating
            for rating in (google_rating, tripadvisor_rating, thefork_rating_5)
            if rating is not None
        ]
        rating_platform_count, rating_avg_5, rating_range_5 = _rating_metrics(ratings)
        platform_count = 1 + int(has_tripadvisor) + int(has_thefork)
        contact_fields = _contact_evidence(google, ta_doc)
        price_fields = _price_evidence(google, ta_doc, tf_doc)

        cuisine = merge_cuisine(
            ta_doc.get("cuisines") if ta_doc else None,
            tf_doc.get("cuisines") if tf_doc else None,
            {"primary_type": google.get("primary_type"), "types": google.get("types")},
        )
        report.cuisine_unmapped.update(cuisine["unmapped"])

        doc = {
            "_id": restaurant_id,
            "integrated_restaurant_id": restaurant_id,
            "canonical_name": google.get("name"),
            "canonical_address": google.get("address"),
            "canonical_street": google.get("street"),
            "canonical_house_number": google.get("house_number"),
            "canonical_postal_code": google.get("postal_code"),
            "canonical_city": google.get("city"),
            "latitude": google.get("latitude"),
            "longitude": google.get("longitude"),
            "coordinate_source": "google",
            **contact_fields,
            **price_fields,
            "has_google": True,
            "has_tripadvisor": has_tripadvisor,
            "has_thefork": has_thefork,
            "has_all_three_platforms": has_tripadvisor and has_thefork,
            "platform_count": platform_count,
            "google_rating_5": google_rating,
            "tripadvisor_rating_5": tripadvisor_rating,
            "thefork_rating_raw_10": thefork_rating_raw,
            "thefork_rating_5": thefork_rating_5,
            "rating_platform_count": rating_platform_count,
            "rating_avg_5": rating_avg_5,
            "rating_range_5": rating_range_5,
            "google_review_count": google.get("review_count"),
            "tripadvisor_review_count": tripadvisor_review_count,
            "thefork_review_count": thefork_review_count,
            "cuisine_tags": cuisine["tags"],
            "cuisine_primary": cuisine["primary"],
            "cuisine_primary_source": cuisine["primary_source"],
            "cuisine_n_sources": cuisine["n_sources"],
            "cuisine_agreement": cuisine["agreement"],
            "integration_flags": sorted(set(integration_flags)),
            "sources": sources,
            "_updated_at": now,
        }
        docs.append(doc)
        report.written += 1

    return docs, report


def unify_collections(
    google_collection: Any,
    tripadvisor_collection: Any,
    thefork_collection: Any,
    candidates_collection: Any,
    links_collection: Any,
    integrated_collection: Any,
    settings: UnifiedSettings,
    *,
    dry_run: bool = False,
    replace_destination: bool = False,
    skip_links: bool = False,
    source: str = SOURCE_ALL,
    writer: Writer = bulk_replace,
) -> UnifiedRunReport:
    """Build selected ER links and the final Google-seeded integrated collection."""
    selected_sources = _selected_sources(source)
    report = UnifiedRunReport(
        dry_run=dry_run,
        replace_destination=replace_destination,
        skip_links=skip_links,
    )

    if skip_links:
        links = list(links_collection.find({"source": {"$in": list(SOURCES)}}))
    else:
        links, link_reports = select_links(candidates_collection, source)
        report.links = link_reports
        if not dry_run:
            for source_report in report.links:
                source_links = [link for link in links if link["source"] == source_report.source]
                (
                    source_report.inserted,
                    source_report.modified,
                    source_report.stale_deleted,
                ) = _upsert_links_for_source(
                    links_collection,
                    source_links,
                    source_report.source,
                    settings,
                    writer,
                    replace=replace_destination,
                )
            if source != SOURCE_ALL:
                other_sources = [s for s in SOURCES if s not in selected_sources]
                existing_other = list(links_collection.find({"source": {"$in": other_sources}}))
                links = links + existing_other

    integrated_docs, integrated_report = build_integrated_docs(
        google_collection,
        tripadvisor_collection,
        thefork_collection,
        links,
    )
    if not dry_run:
        if replace_destination:
            (
                integrated_report.inserted,
                integrated_report.modified,
                integrated_report.stale_deleted,
            ) = _replace_collection_contents(
                integrated_collection,
                integrated_docs,
                settings,
                writer,
            )
        else:
            (
                integrated_report.inserted,
                integrated_report.modified,
                integrated_report.stale_deleted,
            ) = _upsert_and_delete_stale(integrated_collection, integrated_docs, settings, writer)
    report.integrated = integrated_report
    return report


def open_transform_collections(
    settings: UnifiedSettings,
) -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    """Open all Mongo collections, failing fast if Mongo is down."""
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
        db[settings.source_collection_google],
        db[settings.source_collection_tripadvisor],
        db[settings.source_collection_thefork],
        db[settings.candidate_collection],
        db[settings.links_collection],
        db[settings.integrated_collection],
    )
