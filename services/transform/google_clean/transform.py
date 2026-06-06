"""Orchestration + Mongo I/O for the Google Places clean transform.

This is the SINGLE Google transform. It reads ``restaurants_raw_google``, cleans each
record (pure functions in ``cleaners.py``), and idempotently upserts ONE lean document
into ``restaurants_clean_google``, keyed on ``place_id``. Mongo -> Mongo only; the raw
collection is never mutated.

Unlike ``transform.tripadvisor_clean`` there is no geocoding step (Google coordinates
are authoritative and copied verbatim) and no coordinate prefetch/resumability. Drop
rules: the inert junk placeholders (geographic name + no rating) are dropped by default;
``non_dining`` records are kept and flagged unless ``--drop-non-dining`` is set.
Persistence idioms (dual writer, lazy client + ping, key on ``_id``) follow
``services/load/mongo/loader.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pymongo import ReplaceOne
from pymongo.errors import PyMongoError

from .cleaners import clean_record
from .config import CleanSettings

logger = logging.getLogger(__name__)

KEY_FIELD = "place_id"

# A writer persists a batch of prepared docs and returns (inserted, modified).
Writer = Callable[[Any, list[dict[str, Any]]], tuple[int, int]]

_TIER_FIELD = {
    "restaurant": "tier_restaurant",
    "cafe_bar_bakery": "tier_cafe_bar_bakery",
    "non_dining": "tier_non_dining",
    "unknown": "tier_unknown",
}


@dataclass
class CleanReport:
    """Before/after summary of one transform run (also feeds stage-5 quality)."""

    read: int = 0
    written: int = 0
    missing_key: int = 0
    duplicates_collapsed: int = 0
    dropped_junk: int = 0
    dropped_non_dining: int = 0
    stale_deleted: int = 0
    names_normalized: int = 0
    cities_canonicalized: int = 0
    distinct_cities_before: int = 0
    distinct_cities_after: int = 0
    city_out_of_area: int = 0
    address_parts_populated: int = 0
    tier_restaurant: int = 0
    tier_cafe_bar_bakery: int = 0
    tier_non_dining: int = 0
    tier_unknown: int = 0
    is_dining: int = 0
    name_is_geographic: int = 0
    not_operational: int = 0
    with_rating: int = 0
    without_rating: int = 0
    low_review: int = 0
    photos_zero: int = 0


def bulk_upsert(collection: Any, docs: list[dict[str, Any]]) -> tuple[int, int]:
    """Production write path: one batched ``bulk_write`` of ReplaceOne upserts.

    Not exercised by the mongomock unit tests (mongomock cannot execute
    ``bulk_write``); tests inject :func:`serial_upsert`, which yields identical
    collection state.
    """
    if not docs:
        return 0, 0
    ops = [ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs]
    result = collection.bulk_write(ops, ordered=False)
    return result.upserted_count, result.modified_count


def serial_upsert(collection: Any, docs: list[dict[str, Any]]) -> tuple[int, int]:
    """mongomock-compatible write path: per-document ``replace_one`` upserts."""
    inserted = modified = 0
    for doc in docs:
        result = collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        if result.upserted_id is not None:
            inserted += 1
        else:
            modified += result.modified_count
    return inserted, modified


def _prepare(
    raw: dict[str, Any],
    report: CleanReport,
    settings: CleanSettings,
    cities_before: set[str],
    cities_after: set[str],
    dropped_keys: set[Any],
) -> dict[str, Any] | None:
    """Clean a raw record, apply drop rules, update report counters, attach metadata.

    Returns ``None`` (already counted) when the natural key is missing or the record is
    dropped (inert junk, or ``non_dining`` under ``--drop-non-dining``). A dropped
    *keyed* record's key is added to ``dropped_keys`` so the caller can delete any stale
    copy from the destination (rerun convergence when drop settings change). All the
    relevance/quality histogram counters reflect only kept (written) records.
    """
    key = raw.get(KEY_FIELD)
    if key is None or (isinstance(key, str) and key.strip() == ""):
        report.missing_key += 1
        return None

    cleaned = clean_record(raw, low_review_threshold=settings.low_review_threshold)

    raw_city = raw.get("city")
    if raw_city is not None:
        cities_before.add(str(raw_city))

    # Drop rules (counted, then excluded from the kept-record histograms). The key is
    # recorded so a stale copy left by a previous run with different drop settings is
    # deleted from the destination.
    if settings.drop_junk and cleaned["name_is_geographic"] and not cleaned["has_rating"]:
        report.dropped_junk += 1
        dropped_keys.add(key)
        return None
    if settings.drop_non_dining and cleaned["category_tier"] == "non_dining":
        report.dropped_non_dining += 1
        dropped_keys.add(key)
        return None

    if cleaned["name"] is not None and cleaned["name"] != raw.get("name"):
        report.names_normalized += 1
    if cleaned["city"] is not None:
        cities_after.add(cleaned["city"])
        if cleaned["city"] != raw_city:
            report.cities_canonicalized += 1
    if cleaned["city_out_of_area"]:
        report.city_out_of_area += 1
    if cleaned["postal_code"] or cleaned["street"]:
        report.address_parts_populated += 1

    setattr(
        report,
        _TIER_FIELD[cleaned["category_tier"]],
        getattr(report, _TIER_FIELD[cleaned["category_tier"]]) + 1,
    )
    if cleaned["is_dining"]:
        report.is_dining += 1
    if cleaned["name_is_geographic"]:
        report.name_is_geographic += 1
    if cleaned["business_status"] is not None and not cleaned["is_operational"]:
        report.not_operational += 1
    if cleaned["has_rating"]:
        report.with_rating += 1
    else:
        report.without_rating += 1
    if cleaned["low_review"]:
        report.low_review += 1
    if cleaned["photo_count"] == 0:
        report.photos_zero += 1

    doc = dict(cleaned)
    doc["_id"] = key
    doc["_transformed_at"] = datetime.now(UTC)
    doc["_source_collection"] = settings.source_collection
    return doc


def clean_collection(
    source: Any,
    dest: Any,
    settings: CleanSettings,
    *,
    reset: bool = False,
    limit: int | None = None,
    writer: Writer = bulk_upsert,
) -> CleanReport:
    """Clean ``source`` into ``dest`` via idempotent upsert keyed on ``place_id``.

    Each raw record is projected/normalized/classified and upserted as one lean
    document. Re-running converges to the same contents with no duplicates — including
    when drop settings change: a record dropped this run has any stale copy from a
    previous run deleted from the destination.
    """
    if settings.source_collection == settings.destination_collection:
        raise ValueError(
            "source_collection and destination_collection must differ "
            f"(both are {settings.source_collection!r}) — refusing to read and write the "
            "same collection."
        )

    report = CleanReport()
    if reset:
        dest.delete_many({})

    cities_before: set[str] = set()
    cities_after: set[str] = set()
    seen: set[Any] = set()
    dropped_keys: set[Any] = set()
    # Pending docs keyed by _id so a duplicate key within a batch coalesces
    # (last write wins); place_id is unique in practice, so this rarely triggers.
    pending: dict[Any, dict[str, Any]] = {}

    def flush() -> None:
        if not pending:
            return
        writer(dest, list(pending.values()))
        pending.clear()

    cursor = source.find()
    if limit is not None:
        cursor = cursor.limit(limit)

    for raw in cursor:
        report.read += 1
        doc = _prepare(raw, report, settings, cities_before, cities_after, dropped_keys)
        if doc is None:
            continue
        if doc["_id"] in seen:
            report.duplicates_collapsed += 1
        else:
            seen.add(doc["_id"])
            report.written += 1
        pending[doc["_id"]] = doc
        if len(pending) >= settings.batch_size:
            flush()
    flush()

    # Rerun convergence: delete stale destination docs for keys dropped this run (e.g.
    # previously kept as non_dining/junk, now excluded by changed drop settings). Keys
    # also written this run (only possible via duplicate raws) are never deleted.
    stale = dropped_keys - seen
    if stale:
        result = dest.delete_many({"_id": {"$in": list(stale)}})
        report.stale_deleted = result.deleted_count

    report.distinct_cities_before = len(cities_before)
    report.distinct_cities_after = len(cities_after)
    return report


def open_transform_collections(settings: CleanSettings) -> tuple[Any, Any, Any]:
    """Open (client, source, dest) collections, failing fast if Mongo is down.

    ``MongoClient`` connects lazily, so we issue an explicit ``ping`` to force server
    selection. Imported inside the function so tests can monkeypatch
    ``pymongo.MongoClient`` with a mongomock client.
    """
    from pymongo import MongoClient

    client: Any = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except PyMongoError:
        client.close()
        raise
    db = client[settings.mongo_db]
    return client, db[settings.source_collection], db[settings.destination_collection]
