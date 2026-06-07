"""Orchestration + Mongo I/O for the Tripadvisor clean+geocode transform.

DECISION (captured from brainstorming; full rationale in
``specs/tripadvisor-elt-transform.md``):
This is the SINGLE Tripadvisor transform. It reads ``restaurants_raw_tripadvisor``,
cleans each record (pure functions in ``cleaners.py``), geocodes the *cleaned*
address (``geocode.py``), and idempotently upserts ONE document (clean fields +
latitude/longitude) into ``restaurants_clean_tripadvisor``, keyed on ``source_url``.
Geocoding is a sub-step of cleaning, not a separate stage — there is no separate
geocoded collection. Mongo -> Mongo only; the raw collection is never mutated.
Geocoding is resumable (records that already hold coordinates are skipped, so an
interrupted run resumes) and can be skipped entirely via ``skip_geocode`` for a
fast clean-only pass. Persistence idioms (dual writer, lazy client + ping, key on
``_id``) follow ``services/load/mongo/loader.py``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pymongo import ReplaceOne
from pymongo.errors import PyMongoError

from . import geocode as geocode_mod
from .cleaners import clean_record
from .config import CleanSettings

logger = logging.getLogger(__name__)

KEY_FIELD = "source_url"

# A writer persists a batch of prepared docs and returns (inserted, modified).
Writer = Callable[[Any, list[dict[str, Any]]], tuple[int, int]]


def _has_coords(lat: Any, lon: Any) -> bool:
    """A record counts as already geocoded only when *both* coords are present.

    Guards against a partial/corrupt doc (latitude but no longitude) being
    skipped from re-geocoding forever.
    """
    return lat is not None and lon is not None


@dataclass
class CleanReport:
    """Before/after summary of one transform run (also feeds stage-5 quality)."""

    read: int = 0
    written: int = 0
    duplicates_collapsed: int = 0
    missing_key: int = 0
    stale_deleted: int = 0
    # Type repair (activity counters).
    ratings_parsed: int = 0
    ratings_nulled: int = 0
    reviews_parsed: int = 0
    reviews_nulled: int = 0
    nan_coerced: int = 0
    names_normalized: int = 0
    addresses_normalized: int = 0
    # Rich-field parsing coverage.
    photo_count_parsed: int = 0
    price_parsed: int = 0
    cuisines_present: int = 0
    multi_cuisine: int = 0
    opening_hours_parsed: int = 0
    with_reviews: int = 0
    with_phone: int = 0
    with_website: int = 0
    with_email: int = 0
    # Quality-flag coverage.
    with_rating: int = 0
    without_rating: int = 0
    missing_review_count: int = 0
    low_review: int = 0
    rating_with_zero_reviews: int = 0
    # Geocoding.
    geocode_found: int = 0
    geocode_not_found: int = 0
    geocode_skipped_null_addr: int = 0
    geocode_skipped_done: int = 0


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
) -> dict[str, Any] | None:
    """Clean a raw record, update report counters, attach ``_id`` + metadata.

    Returns ``None`` (caller counts ``missing_key``) when the natural key is
    missing/blank, so Mongo never auto-assigns an ObjectId that breaks idempotency.
    """
    key = raw.get(KEY_FIELD)
    if key is None or (isinstance(key, str) and key.strip() == ""):
        return None

    cleaned = clean_record(
        raw,
        low_review_threshold=settings.low_review_threshold,
        review_cap=settings.review_cap,
    )

    # Rating: coverage (with/without) + repair activity (present-but-unparseable -> null).
    if cleaned["rating"] is not None:
        report.ratings_parsed += 1
        report.with_rating += 1
    else:
        report.without_rating += 1
        if not geocode_mod.is_nan(raw.get("rating")):
            report.ratings_nulled += 1

    # Review count: coverage (missing) + repair activity.
    if cleaned["total_review"] is not None:
        report.reviews_parsed += 1
    else:
        report.missing_review_count += 1
        if not geocode_mod.is_nan(raw.get("total_review")):
            report.reviews_nulled += 1

    report.nan_coerced += sum(1 for value in raw.values() if geocode_mod.is_nan(value))

    name = cleaned["restaurant_name"]
    if name is not None and name != raw.get("restaurant_name"):
        report.names_normalized += 1
    address = cleaned["address"]
    if address is not None and address != raw.get("address"):
        report.addresses_normalized += 1

    # Rich-field parsing coverage.
    if cleaned["photo_count"] is not None:
        report.photo_count_parsed += 1
    if cleaned["price_band"] is not None:
        report.price_parsed += 1
    if cleaned["cuisines"]:
        report.cuisines_present += 1
        if len(cleaned["cuisines"]) > 1:
            report.multi_cuisine += 1
    if cleaned["opening_hours"]:
        report.opening_hours_parsed += 1
    if cleaned["has_reviews"]:
        report.with_reviews += 1
    if cleaned["has_phone"]:
        report.with_phone += 1
    if cleaned["has_website"]:
        report.with_website += 1
    if cleaned["has_email"]:
        report.with_email += 1

    # Quality flags.
    if cleaned["low_review"]:
        report.low_review += 1
    if "rating_with_zero_reviews" in cleaned["flags"]:
        report.rating_with_zero_reviews += 1

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
    skip_geocode: bool = False,
    limit: int | None = None,
    geocoder: Any | None = None,
    writer: Writer = bulk_upsert,
) -> CleanReport:
    """Clean + geocode ``source`` into ``dest`` via idempotent upsert.

    Each raw record is cleaned, its cleaned address geocoded (unless skipped or
    already done), and upserted as one document keyed on ``source_url``. Re-running
    converges to the same **key set and content**: on a full run (``limit is None``)
    any destination doc whose ``source_url`` is no longer in the source is deleted
    (``stale_deleted``); a ``--limit`` run is intentionally partial and never
    sync-deletes. Geocoding is resumable: a record that already holds non-null
    coordinates is not re-geocoded. Raises ``ValueError`` if the source and
    destination collection names collide (refusing to read and write one collection).
    """
    if settings.source_collection == settings.destination_collection:
        raise ValueError(
            "source_collection and destination_collection must differ "
            f"(both are {settings.source_collection!r}) — refusing to read and write the "
            "same collection."
        )
    if not skip_geocode and geocoder is None:
        # A missing geocoder is a caller wiring bug, not a legitimate geocode miss
        # (geocode_address would otherwise swallow the AttributeError as not_found).
        raise ValueError("geocoder is required when skip_geocode is False")

    report = CleanReport()
    if reset:
        dest.delete_many({})

    # Prefetch existing coords once: enables resumability (skip already-geocoded)
    # and lets --skip-geocode preserve coordinates a full ReplaceOne would drop.
    existing_coords: dict[Any, tuple[Any, Any]] = {}
    if not reset:
        for doc in dest.find({}, {"latitude": 1, "longitude": 1}):
            existing_coords[doc["_id"]] = (doc.get("latitude"), doc.get("longitude"))

    seen: set[Any] = set()
    # Pending docs are keyed by _id so a duplicate source_url within a batch
    # coalesces (last write wins) — bulk_write(ordered=False) does not guarantee
    # order for repeated _ids and can even raise duplicate-key errors otherwise.
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
            report.missing_key += 1
            continue
        if doc["_id"] in seen:
            # Same key seen earlier this run: the upsert collapses both to one
            # doc (last write wins). Count the collapse but not a second write.
            report.duplicates_collapsed += 1
        else:
            seen.add(doc["_id"])
            report.written += 1  # distinct docs upserted

        prev_lat, prev_lon = existing_coords.get(doc["_id"], (None, None))
        if skip_geocode:
            # Preserve any coords already on disk; do not call Nominatim.
            doc["latitude"], doc["longitude"] = prev_lat, prev_lon
        elif _has_coords(prev_lat, prev_lon):
            doc["latitude"], doc["longitude"] = prev_lat, prev_lon
            report.geocode_skipped_done += 1
        elif geocode_mod.is_nan(doc.get("address")):
            doc["latitude"], doc["longitude"] = None, None
            report.geocode_skipped_null_addr += 1
        else:
            lat, lon = geocode_mod.geocode_one(geocoder, doc, settings)
            doc["latitude"], doc["longitude"] = lat, lon
            if lat is not None:
                report.geocode_found += 1
            else:
                report.geocode_not_found += 1
                doc["flags"].append("geocode_not_found")
            time.sleep(settings.delay_seconds)  # Nominatim rate limit (>= 1 req/s)

        # Coordinate-derived quality flags (the clean_record pure layer cannot see coords).
        doc["has_coordinates"] = _has_coords(doc["latitude"], doc["longitude"])
        if not doc["has_coordinates"]:
            doc["flags"].append("missing_coordinates")

        pending[doc["_id"]] = doc  # coalesce by key (last write wins)
        if len(pending) >= settings.batch_size:
            flush()
    flush()

    # Rerun convergence: on a full run, delete destination docs whose source_url vanished
    # from the source (venues delisted upstream). Skipped for a partial --limit run, which
    # is intentionally incomplete and must not delete the records it didn't read. This
    # layer is flag-first (only missing-key records are skipped), so `seen` is exactly the
    # set of keys that should survive a full run.
    if limit is None:
        result = dest.delete_many({"_id": {"$nin": list(seen)}})
        report.stale_deleted = result.deleted_count

    return report


def open_transform_collections(settings: CleanSettings) -> tuple[Any, Any, Any]:
    """Open (client, source, dest) collections, failing fast if Mongo is down.

    ``MongoClient`` connects lazily, so we issue an explicit ``ping`` to force
    server selection. Imported inside the function so tests can monkeypatch
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
