from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pymongo.errors import PyMongoError

from .config import ClickHouseLoaderSettings
from .targets import TargetSpec

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000

# A writer receives the ClickHouse client, the table name, a list of flat row
# dicts, and the ordered column-name list, and returns the number of rows inserted.
Writer = Callable[[Any, str, list[dict[str, Any]], list[str]], int]


@dataclass
class LoadReport:
    """Summary of one Mongo → ClickHouse target load."""

    source: str
    collection: str
    read: int = 0
    inserted: int = 0
    skipped: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)

    def _skip(self, reason: str) -> None:
        self.skipped += 1
        self.skipped_reasons[reason] = self.skipped_reasons.get(reason, 0) + 1


# ---------------------------------------------------------------------------
# Writer implementations
# ---------------------------------------------------------------------------


def ch_insert(
    ch_client: Any,
    table: str,
    rows: list[dict[str, Any]],
    column_order: list[str],
) -> int:
    """Production write path: batch INSERT via clickhouse-connect."""
    if not rows:
        return 0
    data = [[row[col] for col in column_order] for row in rows]
    ch_client.insert(table, data, column_names=column_order)
    return len(rows)


def list_collect(
    _ch_client: Any,
    _table: str,
    rows: list[dict[str, Any]],
    _column_order: list[str],
) -> int:
    """Test-friendly writer: a no-op that just returns the row count.

    Tests that need to inspect the rows inject their own writer via a closure
    or use a ``FakeWriter`` helper defined in the test file.
    """
    return len(rows)


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def open_mongo(settings: ClickHouseLoaderSettings, collection_name: str) -> tuple[Any, Any]:
    """Open a MongoDB client and return ``(client, collection)``.

    ``MongoClient`` connects lazily, so we issue an explicit ``ping`` to fail
    fast if MongoDB is unreachable.  The import lives *inside* this function so
    tests can monkeypatch ``pymongo.MongoClient`` with a mongomock client.
    """
    from pymongo import MongoClient

    client: Any = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except PyMongoError:
        client.close()
        raise
    collection = client[settings.mongo_db][collection_name]
    return client, collection


def open_clickhouse(settings: ClickHouseLoaderSettings) -> Any:
    """Open a ClickHouse client and verify connectivity.

    The ``clickhouse_connect`` import lives *inside* this function so tests can
    monkeypatch it with a fake client.  We issue a cheap ``SELECT 1`` to fail
    fast if ClickHouse is unreachable.
    """
    import clickhouse_connect  # type: ignore[import]

    # Connect without a target database first so we can bootstrap it: the
    # destination DB does not exist on a fresh ClickHouse volume, and selecting
    # a missing database at connect time raises UNKNOWN_DATABASE.
    client = clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
    )
    client.command("SELECT 1")
    client.command(f"CREATE DATABASE IF NOT EXISTS {settings.clickhouse_db}")
    client.database = settings.clickhouse_db
    return client


# ---------------------------------------------------------------------------
# Core load function
# ---------------------------------------------------------------------------


def load_target(
    spec: TargetSpec,
    mongo_collection: Any,
    ch_client: Any,
    *,
    writer: Writer = ch_insert,
    batch_size: int = BATCH_SIZE,
    recreate: bool = False,
) -> LoadReport:
    """Load one Mongo collection into a ClickHouse table.

    Steps:
    1. Ensure the table exists (``CREATE TABLE IF NOT EXISTS``). When ``recreate``
       is set, ``DROP TABLE`` first so schema changes (new/changed columns) take
       effect — a plain ``CREATE IF NOT EXISTS`` leaves an existing table's schema
       untouched, so new columns would never appear.
    2. Truncate the table (full-reload semantics; idempotent).
    3. Stream all docs from Mongo, project each to a flat row, skip on None.
    4. Flush rows to ClickHouse in ``batch_size`` chunks.

    The ``writer`` seam lets tests inject a fake without touching I/O.
    """
    db = ch_client.database if hasattr(ch_client, "database") else "dataman"
    ddl = spec.ddl.format(db=db)
    table = f"{db}.{spec.table}"

    report = LoadReport(source=spec.name, collection=spec.table)

    # 1. Create table (dropping first when a schema change must be applied).
    if recreate:
        ch_client.command(f"DROP TABLE IF EXISTS {table}")
    ch_client.command(ddl)
    # 2. Truncate for idempotent reload
    ch_client.command(f"TRUNCATE TABLE IF EXISTS {table}")

    batch: list[dict[str, Any]] = []

    def flush() -> None:
        if not batch:
            return
        inserted = writer(ch_client, table, batch, spec.column_order)
        report.inserted += inserted
        batch.clear()

    # 3 + 4. Stream, project, batch, flush
    for raw_doc in mongo_collection.find({}):
        report.read += 1
        row = spec.projector(raw_doc)
        if row is None:
            report._skip("missing_key")
            continue
        batch.append(row)
        if len(batch) >= batch_size:
            flush()
    flush()

    logger.info(
        "Loaded %s → %s: read=%d inserted=%d skipped=%d",
        spec.mongo_collection,
        table,
        report.read,
        report.inserted,
        report.skipped,
    )
    return report
