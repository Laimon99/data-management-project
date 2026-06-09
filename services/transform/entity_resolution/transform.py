"""Orchestration + Mongo I/O for the entity-resolution transform."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pymongo import UpdateOne
from pymongo.errors import PyMongoError

from .blocking import BlockedPair, geo_block, has_coordinates, postal_name_block
from .chains import chain_info_for_pair
from .config import ERSettings
from .features import compute_features
from .scoring import MATCH, UNBLOCKABLE, UNCERTAIN, label, score_components

SOURCE_TRIPADVISOR = "tripadvisor"
SOURCE_THEFORK = "thefork"
SOURCE_ALL = "all"
LABELS = (MATCH, "NON_MATCH", "UNCERTAIN", UNBLOCKABLE)
BLOCK_SOURCES = ("geo", "postal_code", "fast_path", "unblockable")

GOOGLE_PROJECTION = {
    "_id": 1,
    "place_id": 1,
    "name": 1,
    "latitude": 1,
    "longitude": 1,
    "street": 1,
    "house_number": 1,
    "postal_code": 1,
    "phone": 1,
    "website": 1,
    "cuisines": 1,
}
TRIPADVISOR_PROJECTION = {
    "_id": 1,
    "ta_location_id": 1,
    "restaurant_name": 1,
    "latitude": 1,
    "longitude": 1,
    "has_coordinates": 1,
    "street": 1,
    "house_number": 1,
    "postal_code": 1,
    "phone": 1,
    "website": 1,
    "cuisines": 1,
}
THEFORK_PROJECTION = {
    "_id": 1,
    "tf_id": 1,
    "restaurant_name": 1,
    "latitude": 1,
    "longitude": 1,
    "street": 1,
    "house_number": 1,
    "postal_code": 1,
    "cuisines": 1,
}

# A writer persists a batch of prepared candidate docs and returns
# (inserted, modified, skipped_protected).
Writer = Callable[[Any, list[dict[str, Any]]], tuple[int, int, int]]


@dataclass
class SourceRunReport:
    source: str
    dmin: float = 0.0
    dmax: float = 0.0
    chain_dmin: float = 0.0
    chain_dmax: float = 0.0
    google_read: int = 0
    source_read: int = 0
    generated_pairs: dict[str, int] = field(default_factory=lambda: {"geo": 0, "postal_code": 0})
    block_counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(BLOCK_SOURCES, 0))
    label_counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(LABELS, 0))
    candidates: int = 0
    inserted: int = 0
    modified: int = 0
    skipped_protected: int = 0
    deleted_existing: int = 0
    chain_candidates: int = 0
    chain_hardened: int = 0


@dataclass
class ERRunReport:
    dry_run: bool
    replace_destination: bool
    dmin: float
    dmax: float
    source_thresholds: dict[str, dict[str, float]]
    chain_source_thresholds: dict[str, dict[str, float]]
    sources: list[SourceRunReport] = field(default_factory=list)


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _has_postal_code(doc: dict[str, Any]) -> bool:
    return not _is_blank(doc.get("postal_code"))


def _google_id(doc: dict[str, Any]) -> str:
    value = doc.get("place_id")
    if _is_blank(value):
        value = doc.get("_id")
    return str(value)


def source_id(doc: dict[str, Any], source: str) -> str:
    key = "ta_location_id" if source == SOURCE_TRIPADVISOR else "tf_id"
    value = doc.get(key)
    if _is_blank(value):
        value = doc.get("_id")
    return str(value)


def _phone_fast_path(google_doc: dict[str, Any], source_doc: dict[str, Any]) -> bool:
    google_phone = google_doc.get("phone")
    source_phone = source_doc.get("phone")
    return not _is_blank(google_phone) and google_phone == source_phone


def _website_fast_path(google_doc: dict[str, Any], source_doc: dict[str, Any]) -> bool:
    google_website = google_doc.get("website")
    source_website = source_doc.get("website")
    return not _is_blank(google_website) and google_website == source_website


def _fast_path(
    google_doc: dict[str, Any],
    source_doc: dict[str, Any],
    *,
    allow_website: bool = True,
) -> str | None:
    if _phone_fast_path(google_doc, source_doc):
        return "phone"
    if allow_website and _website_fast_path(google_doc, source_doc):
        return "website"
    return None


def _chain_hardened_label(
    candidate_label: str,
    components: dict[str, float | None],
    settings: ERSettings,
    *,
    is_chain: bool,
    phone_fast_path: bool,
    chain_hardening: list[str],
) -> str:
    if not is_chain or phone_fast_path:
        return candidate_label
    if candidate_label not in {MATCH, UNCERTAIN}:
        return candidate_label

    geo_dist_m = components.get("geo_dist_m")
    if geo_dist_m is None:
        chain_hardening.append("chain_no_geo_evidence")
        return UNCERTAIN if candidate_label == MATCH else candidate_label

    if geo_dist_m > settings.chain_auto_match_radius_m:
        chain_hardening.append("chain_distance_gt_auto_match_radius")
        return UNCERTAIN if candidate_label == MATCH else candidate_label

    return candidate_label


def _candidate_doc(
    pair: BlockedPair,
    source: str,
    settings: ERSettings,
    *,
    allow_fast_path: bool,
) -> dict[str, Any]:
    components = compute_features(pair.google, pair.source, source)
    chain_info = chain_info_for_pair(pair.google, pair.source)
    chain_hardening: list[str] = []
    dmin, dmax = settings.thresholds_for_source(source, is_chain=chain_info.is_chain)

    phone_fast_path = _phone_fast_path(pair.google, pair.source)
    website_fast_path = _website_fast_path(pair.google, pair.source)
    if allow_fast_path and chain_info.is_chain and website_fast_path:
        chain_hardening.append("chain_website_fast_path_suppressed")
    fast_path = (
        _fast_path(
            pair.google,
            pair.source,
            allow_website=not chain_info.is_chain,
        )
        if allow_fast_path
        else None
    )

    if fast_path is not None:
        block_source = "fast_path"
        score = 1.0
        candidate_label = MATCH
    else:
        block_source = pair.block_source
        score = score_components(components, source)
        candidate_label = label(score, dmin, dmax)
        candidate_label = _chain_hardened_label(
            candidate_label,
            components,
            settings,
            is_chain=chain_info.is_chain,
            phone_fast_path=phone_fast_path,
            chain_hardening=chain_hardening,
        )

    google_id = _google_id(pair.google)
    source_value = source_id(pair.source, source)
    return {
        "_id": f"{google_id}:{source_value}",
        "google_id": google_id,
        "source": source,
        "source_id": source_value,
        "block_source": block_source,
        "fast_path": fast_path,
        "score": score,
        "dmin": dmin,
        "dmax": dmax,
        "is_chain": chain_info.is_chain,
        "chain_brand": chain_info.brand,
        "chain_hardening": chain_hardening,
        "components": components,
        "label": candidate_label,
        "llm_label": None,
        "_created_at": datetime.now(UTC),
    }


def _unblockable_doc(source_doc: dict[str, Any]) -> dict[str, Any]:
    source_value = source_id(source_doc, SOURCE_TRIPADVISOR)
    return {
        "_id": f"unblockable:tripadvisor:{source_value}",
        "google_id": None,
        "source": SOURCE_TRIPADVISOR,
        "source_id": source_value,
        "block_source": "unblockable",
        "fast_path": None,
        "score": None,
        "dmin": None,
        "dmax": None,
        "is_chain": False,
        "chain_brand": None,
        "chain_hardening": [],
        "components": {},
        "label": UNBLOCKABLE,
        "llm_label": None,
        "_created_at": datetime.now(UTC),
    }


def _count_candidate(report: SourceRunReport, doc: dict[str, Any]) -> None:
    report.candidates += 1
    report.block_counts[doc["block_source"]] = report.block_counts.get(doc["block_source"], 0) + 1
    report.label_counts[doc["label"]] = report.label_counts.get(doc["label"], 0) + 1
    if doc.get("is_chain") is True:
        report.chain_candidates += 1
    if doc.get("chain_hardening"):
        report.chain_hardened += 1


def _build_tripadvisor_candidates(
    google_docs: list[dict[str, Any]],
    source_docs: list[dict[str, Any]],
    settings: ERSettings,
) -> tuple[list[dict[str, Any]], SourceRunReport]:
    report = SourceRunReport(
        source=SOURCE_TRIPADVISOR,
        dmin=settings.thresholds_for_source(SOURCE_TRIPADVISOR)[0],
        dmax=settings.thresholds_for_source(SOURCE_TRIPADVISOR)[1],
        chain_dmin=settings.thresholds_for_source(SOURCE_TRIPADVISOR, is_chain=True)[0],
        chain_dmax=settings.thresholds_for_source(SOURCE_TRIPADVISOR, is_chain=True)[1],
        google_read=len(google_docs),
        source_read=len(source_docs),
    )

    with_coords = [doc for doc in source_docs if has_coordinates(doc)]
    without_coords = [doc for doc in source_docs if not has_coordinates(doc)]
    postal_eligible = [doc for doc in without_coords if _has_postal_code(doc)]
    unblockable = [doc for doc in without_coords if not _has_postal_code(doc)]

    geo_pairs = geo_block(google_docs, with_coords, settings.geo_block_radius_m)
    postal_pairs = postal_name_block(google_docs, postal_eligible)
    report.generated_pairs["geo"] = len(geo_pairs)
    report.generated_pairs["postal_code"] = len(postal_pairs)

    docs: list[dict[str, Any]] = []
    for pair in geo_pairs:
        doc = _candidate_doc(pair, SOURCE_TRIPADVISOR, settings, allow_fast_path=False)
        docs.append(doc)
        _count_candidate(report, doc)
    for pair in postal_pairs:
        doc = _candidate_doc(pair, SOURCE_TRIPADVISOR, settings, allow_fast_path=True)
        docs.append(doc)
        _count_candidate(report, doc)
    for source_doc in unblockable:
        doc = _unblockable_doc(source_doc)
        docs.append(doc)
        _count_candidate(report, doc)

    return docs, report


def _build_thefork_candidates(
    google_docs: list[dict[str, Any]],
    source_docs: list[dict[str, Any]],
    settings: ERSettings,
) -> tuple[list[dict[str, Any]], SourceRunReport]:
    report = SourceRunReport(
        source=SOURCE_THEFORK,
        dmin=settings.thresholds_for_source(SOURCE_THEFORK)[0],
        dmax=settings.thresholds_for_source(SOURCE_THEFORK)[1],
        chain_dmin=settings.thresholds_for_source(SOURCE_THEFORK, is_chain=True)[0],
        chain_dmax=settings.thresholds_for_source(SOURCE_THEFORK, is_chain=True)[1],
        google_read=len(google_docs),
        source_read=len(source_docs),
    )
    geo_pairs = geo_block(google_docs, source_docs, settings.geo_block_radius_m)
    report.generated_pairs["geo"] = len(geo_pairs)

    docs: list[dict[str, Any]] = []
    for pair in geo_pairs:
        doc = _candidate_doc(pair, SOURCE_THEFORK, settings, allow_fast_path=False)
        docs.append(doc)
        _count_candidate(report, doc)
    return docs, report


def _update_doc(doc: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in doc.items() if key not in {"_id", "_created_at"}}


def _filter_unprotected(
    collection: Any,
    docs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    ids = [doc["_id"] for doc in docs]
    protected = {
        doc["_id"]
        for doc in collection.find(
            {"_id": {"$in": ids}, "llm_label": {"$exists": True, "$ne": None}},
            {"_id": 1},
        )
    }
    return [doc for doc in docs if doc["_id"] not in protected], len(protected)


def bulk_upsert(collection: Any, docs: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Production write path: batched update upserts that preserve LLM decisions."""
    if not docs:
        return 0, 0, 0

    docs_to_write, skipped = _filter_unprotected(collection, docs)
    if not docs_to_write:
        return 0, 0, skipped

    ops = [
        UpdateOne(
            {"_id": doc["_id"]},
            {
                "$set": _update_doc(doc),
                "$setOnInsert": {"_created_at": doc["_created_at"]},
            },
            upsert=True,
        )
        for doc in docs_to_write
    ]
    result = collection.bulk_write(ops, ordered=False)
    return result.upserted_count, result.modified_count, skipped


def serial_upsert(collection: Any, docs: list[dict[str, Any]]) -> tuple[int, int, int]:
    """mongomock-compatible write path mirroring :func:`bulk_upsert`."""
    inserted = modified = skipped = 0
    for doc in docs:
        existing = collection.find_one({"_id": doc["_id"]}, {"llm_label": 1})
        if existing is not None and existing.get("llm_label") is not None:
            skipped += 1
            continue
        result = collection.update_one(
            {"_id": doc["_id"]},
            {
                "$set": _update_doc(doc),
                "$setOnInsert": {"_created_at": doc["_created_at"]},
            },
            upsert=True,
        )
        if result.upserted_id is not None:
            inserted += 1
        else:
            modified += result.modified_count
    return inserted, modified, skipped


def _flush_batches(
    collection: Any,
    docs: list[dict[str, Any]],
    settings: ERSettings,
    writer: Writer,
) -> tuple[int, int, int]:
    inserted = modified = skipped = 0
    for start in range(0, len(docs), settings.batch_size):
        batch = docs[start : start + settings.batch_size]
        batch_inserted, batch_modified, batch_skipped = writer(collection, batch)
        inserted += batch_inserted
        modified += batch_modified
        skipped += batch_skipped
    return inserted, modified, skipped


def _delete_existing_source(collection: Any, source: str) -> int:
    result = collection.delete_many({"source": source})
    return int(result.deleted_count)


def _selected_sources(source: str) -> tuple[str, ...]:
    if source == SOURCE_ALL:
        return SOURCE_TRIPADVISOR, SOURCE_THEFORK
    if source in {SOURCE_TRIPADVISOR, SOURCE_THEFORK}:
        return (source,)
    raise ValueError("source must be one of: tripadvisor, thefork, all")


def resolve_collections(
    google_collection: Any,
    tripadvisor_collection: Any,
    thefork_collection: Any,
    destination_collection: Any,
    settings: ERSettings,
    *,
    source: str = SOURCE_ALL,
    dry_run: bool = False,
    replace_destination: bool = False,
    writer: Writer = bulk_upsert,
) -> ERRunReport:
    """Run ER for the selected source collections."""
    selected = _selected_sources(source)
    source_thresholds = {
        source_name: {
            "dmin": settings.thresholds_for_source(source_name)[0],
            "dmax": settings.thresholds_for_source(source_name)[1],
        }
        for source_name in selected
    }
    chain_source_thresholds = {
        source_name: {
            "dmin": settings.thresholds_for_source(source_name, is_chain=True)[0],
            "dmax": settings.thresholds_for_source(source_name, is_chain=True)[1],
        }
        for source_name in selected
    }
    report = ERRunReport(
        dry_run=dry_run,
        replace_destination=replace_destination,
        dmin=settings.dmin,
        dmax=settings.dmax,
        source_thresholds=source_thresholds,
        chain_source_thresholds=chain_source_thresholds,
    )
    google_docs = list(
        google_collection.find(
            {"is_dining": True, "is_operational": True},
            GOOGLE_PROJECTION,
        )
    )

    for source_name in selected:
        if source_name == SOURCE_TRIPADVISOR:
            source_docs = list(tripadvisor_collection.find({}, TRIPADVISOR_PROJECTION))
            docs, source_report = _build_tripadvisor_candidates(google_docs, source_docs, settings)
        else:
            source_docs = list(thefork_collection.find({}, THEFORK_PROJECTION))
            docs, source_report = _build_thefork_candidates(google_docs, source_docs, settings)

        if not dry_run:
            if replace_destination:
                source_report.deleted_existing = _delete_existing_source(
                    destination_collection,
                    source_name,
                )
            inserted, modified, skipped = _flush_batches(
                destination_collection,
                docs,
                settings,
                writer,
            )
            source_report.inserted = inserted
            source_report.modified = modified
            source_report.skipped_protected = skipped
        report.sources.append(source_report)

    return report


def open_transform_collections(settings: ERSettings) -> tuple[Any, Any, Any, Any, Any]:
    """Open (client, google, tripadvisor, thefork, dest), failing fast if Mongo is down."""
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
        db[settings.destination_collection],
    )
