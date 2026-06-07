"""Orchestration + Mongo I/O for the TheFork clean transform.

This is the SINGLE TheFork transform — the ``T`` of the ELT pipeline for TheFork. It
reads ``restaurants_raw_thefork``, cleans each record (pure functions in ``cleaners.py``),
and idempotently upserts ONE lean document into ``restaurants_clean_thefork``, keyed on
``source_id``. Mongo -> Mongo only; the raw collection is never mutated.

Unlike ``transform.tripadvisor_clean`` there is **no geocoding** (TheFork coordinates are
authoritative) and **no type-repair** (fields arrive already typed). Unlike
``transform.google_clean`` there are **no drop rules** (the slice is duplicate-free and
100% dining): every raw record is kept and annotated with count-only flags. Persistence
idioms (dual writer, lazy client + ping, key on ``_id``) follow
``services/load/mongo/loader.py`` and the sibling transforms.
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

KEY_FIELD = "source_id"

# A writer persists a batch of prepared docs and returns (inserted, modified).
Writer = Callable[[Any, list[dict[str, Any]]], tuple[int, int]]


@dataclass
class CleanReport:
    """Before/after summary of one transform run (also feeds stage-5 quality)."""

    read: int = 0
    written: int = 0
    missing_key: int = 0
    duplicates_collapsed: int = 0
    stale_deleted: int = 0
    names_normalized: int = 0
    cities_normalized: int = 0
    street_parsed: int = 0
    house_number_parsed: int = 0
    postal_code_parsed: int = 0
    avg_price_parsed: int = 0
    discount_present: int = 0
    discount_pct_parsed: int = 0
    discount_noise_dropped: int = 0
    opening_hours_parsed: int = 0
    cuisines_present: int = 0
    multi_cuisine: int = 0
    dietary_tagged: int = 0
    invalid_cuisine_type: int = 0
    with_rating: int = 0
    without_rating: int = 0
    missing_review_count: int = 0
    low_review: int = 0
    with_reviews: int = 0
    rating_sample_divergent: int = 0


def bulk_upsert(collection: Any, docs: list[dict[str, Any]]) -> tuple[int, int]:
    """Production write path: one batched ``bulk_write`` of ReplaceOne upserts.

    Not exercised by the mongomock unit tests (mongomock cannot execute ``bulk_write``);
    tests inject :func:`serial_upsert`, which yields identical collection state.
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
    raw: dict[str, Any], report: CleanReport, settings: CleanSettings
) -> dict[str, Any] | None:
    """Clean a raw record, update report counters, attach metadata.

    Returns ``None`` (already counted) only when the natural key is missing. There are no
    drop rules: every keyed record is kept. The histogram counters reflect kept records.
    """
    key = raw.get(KEY_FIELD)
    if key is None or (isinstance(key, str) and key.strip() == ""):
        report.missing_key += 1
        return None

    cleaned = clean_record(
        raw,
        low_review_threshold=settings.low_review_threshold,
        review_cap=settings.review_cap,
    )

    if cleaned["restaurant_name"] is not None and cleaned["restaurant_name"] != raw.get(
        "restaurant_name"
    ):
        report.names_normalized += 1
    if cleaned["city"] is not None and cleaned["city"] != raw.get("city"):
        report.cities_normalized += 1
    if cleaned["street"]:
        report.street_parsed += 1
    if cleaned["house_number"]:
        report.house_number_parsed += 1
    if cleaned["postal_code"]:
        report.postal_code_parsed += 1
    if cleaned["avg_price_eur"] is not None:
        report.avg_price_parsed += 1
    if cleaned["has_discount"]:
        report.discount_present += 1
        if cleaned["discount_pct"] is not None:
            report.discount_pct_parsed += 1
        else:
            report.discount_noise_dropped += 1
    if cleaned["opening_hours"]:
        report.opening_hours_parsed += 1
    if cleaned["cuisines"]:
        report.cuisines_present += 1
        if len(cleaned["cuisines"]) > 1:
            report.multi_cuisine += 1
    if cleaned["dietary_options"]:
        report.dietary_tagged += 1
    if "invalid_cuisine_type" in cleaned["flags"]:
        report.invalid_cuisine_type += 1
    if cleaned["has_rating"]:
        report.with_rating += 1
    else:
        report.without_rating += 1
    if not cleaned["has_review_count"]:
        report.missing_review_count += 1
    if cleaned["low_review"]:
        report.low_review += 1
    if cleaned["has_reviews"]:
        report.with_reviews += 1
    if cleaned["rating_sample_divergent"]:
        report.rating_sample_divergent += 1

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
    """Clean ``source`` into ``dest`` via idempotent upsert keyed on ``source_id``.

    Each raw record is parsed/normalized/flagged and upserted as one lean document.
    Re-running converges to the same **key set and content** (run metadata such as
    ``_transformed_at`` aside): on a **full run** (``limit is None``) any destination doc
    whose ``source_id`` is no longer in the source is deleted, so venues dropped upstream
    (the 2026-06-06 scrape dropped 6 and added 6) do not linger. A ``--limit`` run is
    intentionally partial and never sync-deletes.
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

    seen: set[Any] = set()
    # Pending docs keyed by _id so a duplicate key within a batch coalesces (last write
    # wins); source_id is unique in practice, so this rarely triggers.
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
        doc = _prepare(raw, report, settings)
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

    # Rerun convergence: on a full run, delete destination docs whose key vanished from the
    # source (e.g. venues delisted upstream). Skipped for a partial --limit run, which is
    # intentionally incomplete and must not delete the records it didn't read.
    if limit is None:
        result = dest.delete_many({"_id": {"$nin": list(seen)}})
        report.stale_deleted = result.deleted_count

    return report


def open_transform_collections(settings: CleanSettings) -> tuple[Any, Any, Any]:
    """Open (client, source, dest) collections, failing fast if Mongo is down.

    ``MongoClient`` connects lazily, so we issue an explicit ``ping`` to force server
    selection. Imported inside the function so tests can monkeypatch ``pymongo.MongoClient``
    with a mongomock client.
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
