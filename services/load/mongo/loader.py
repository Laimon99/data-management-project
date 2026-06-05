from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pymongo import ReplaceOne
from pymongo.errors import PyMongoError

from .config import LoaderSettings
from .sources import SourceSpec

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000

# A writer persists a batch of prepared docs and returns (inserted, modified) counts.
Writer = Callable[[Any, list[dict[str, Any]]], tuple[int, int]]


@dataclass
class LoadReport:
    """Summary of one source load."""

    source: str
    collection: str
    read: int = 0
    inserted: int = 0
    modified: int = 0
    skipped: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)

    def _skip(self, reason: str) -> None:
        self.skipped += 1
        self.skipped_reasons[reason] = self.skipped_reasons.get(reason, 0) + 1


def _iter_raw_records(spec: SourceSpec, report: LoadReport) -> Iterator[dict[str, Any]]:
    """Yield parsed records from a raw file according to its format.

    ``jsonl`` is streamed line by line so large files (~249 MB) are never fully
    materialized. Malformed jsonl lines are skipped, counted, and logged with
    their line number; the rest of the file still loads.
    """

    if spec.fmt == "jsonl":
        with spec.raw_file.open("r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("%s: skipping malformed jsonl line %d", spec.name, lineno)
                    report._skip("malformed_line")
                    continue
                report.read += 1
                yield record
    elif spec.fmt == "json_array":
        with spec.raw_file.open("r", encoding="utf-8") as f:
            try:
                records = json.load(f)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{spec.name}: {spec.raw_file} is not valid JSON: {exc}") from exc
        if not isinstance(records, list):
            raise ValueError(
                f"{spec.name}: expected a top-level JSON array in {spec.raw_file}, "
                f"got {type(records).__name__}"
            )
        for record in records:
            report.read += 1
            yield record
    else:  # pragma: no cover - guarded by Literal type
        raise ValueError(f"Unknown format: {spec.fmt}")


def _prepare(record: dict[str, Any], spec: SourceSpec) -> dict[str, Any] | None:
    """Set ``_id`` from the natural key and attach minimal load metadata.

    Returns ``None`` (caller skips) when the natural key is missing/null/empty,
    so Mongo never auto-assigns an ObjectId that would break idempotency.
    """

    key = record.get(spec.key_field)
    if key is None or (isinstance(key, str) and key.strip() == ""):
        return None
    doc = dict(record)
    doc["_id"] = key
    doc["_loaded_at"] = datetime.now(UTC)
    doc["_source_file"] = str(spec.raw_file)
    return doc


def bulk_upsert(collection: Any, docs: list[dict[str, Any]]) -> tuple[int, int]:
    """Production write path: one batched ``bulk_write`` of ReplaceOne upserts.

    Far fewer server round-trips than per-document writes. This path is *not*
    exercised by the mongomock unit tests — mongomock 4.3.0 rejects the ``sort``
    kwarg pymongo injects into bulk replace ops (fixed only on mongomock's
    unreleased ``develop``). It is covered instead by the real-Mongo integration
    test (``tests/load/mongo/test_integration.py``).
    """

    if not docs:
        return 0, 0
    ops = [ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs]
    result = collection.bulk_write(ops, ordered=False)
    return result.upserted_count, result.modified_count


def serial_upsert(collection: Any, docs: list[dict[str, Any]]) -> tuple[int, int]:
    """mongomock-compatible write path: per-document ``replace_one`` upserts.

    Produces the same collection state as :func:`bulk_upsert`; used by the unit
    tests that run against mongomock.
    """

    inserted = modified = 0
    for doc in docs:
        result = collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        if result.upserted_id is not None:
            inserted += 1
        else:
            modified += result.modified_count
    return inserted, modified


def load_source(
    spec: SourceSpec,
    collection: Any,
    *,
    reset: bool = False,
    batch_size: int = BATCH_SIZE,
    writer: Writer = bulk_upsert,
) -> LoadReport:
    """Load one source into a MongoDB collection via idempotent upsert.

    Records are stored as a raw passthrough (original fields verbatim plus load
    metadata). Each document is keyed on ``_id`` (the source's natural key) and
    upserted in batches of ``batch_size``, so re-running converges to the same
    contents with no duplicates.

    The actual persistence is delegated to ``writer`` (default :func:`bulk_upsert`,
    a batched ``bulk_write``). Unit tests inject :func:`serial_upsert` because
    mongomock cannot execute ``bulk_write``; the default batched path is verified by
    the real-Mongo integration test. Batching keeps memory bounded — at most
    ``batch_size`` prepared docs are held at once, so the ~249 MB Google JSONL file
    still streams without being fully materialized.
    """

    report = LoadReport(source=spec.name, collection=spec.collection)
    if reset:
        collection.delete_many({})

    batch: list[dict[str, Any]] = []

    def flush() -> None:
        if not batch:
            return
        inserted, modified = writer(collection, batch)
        report.inserted += inserted
        report.modified += modified
        batch.clear()

    for record in _iter_raw_records(spec, report):
        doc = _prepare(record, spec)
        if doc is None:
            report._skip("missing_key")
            continue
        batch.append(doc)
        if len(batch) >= batch_size:
            flush()
    flush()
    return report


def open_collection(settings: LoaderSettings, spec: SourceSpec) -> tuple[Any, Any]:
    """Open a Mongo client/collection for a source, failing fast if unreachable.

    ``MongoClient`` connects lazily, so we issue an explicit ``ping`` here to force
    server selection. Without it, a load that performs no writes (empty file, or a
    file where every record is skipped) could report success even when MongoDB is
    down.
    """

    # Imported here (not at module top) so tests can monkeypatch
    # ``pymongo.MongoClient`` with a mongomock client.
    from pymongo import MongoClient

    client: Any = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except PyMongoError:
        client.close()
        raise
    collection = client[settings.mongo_db][spec.collection]
    return client, collection
