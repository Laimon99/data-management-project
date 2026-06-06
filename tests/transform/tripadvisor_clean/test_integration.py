"""Integration tests against a real MongoDB for the default bulk_write path.

``clean_collection`` defaults to :func:`bulk_upsert` (batched ``bulk_write``), which
mongomock 4.3.0 cannot execute, so the mongomock unit tests inject ``serial_upsert``.
These cover the production path against the MongoDB at ``DATAMAN_MONGO_URI`` (default
``mongodb://localhost:27017``) and **auto-skip** when no server is reachable.

Run explicitly with::

    docker compose up -d mongo
    uv run pytest tests/transform/tripadvisor_clean/test_integration.py
"""

from __future__ import annotations

import os

import pytest

from transform.tripadvisor_clean.config import CleanSettings
from transform.tripadvisor_clean.transform import clean_collection

pymongo = pytest.importorskip("pymongo")
from pymongo.errors import PyMongoError  # noqa: E402

MONGO_URI = os.environ.get("DATAMAN_MONGO_URI", "mongodb://localhost:27017")
TEST_DB = "dataman_transform_it"


@pytest.fixture
def real_db():
    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
    try:
        client.admin.command("ping")
    except PyMongoError:
        client.close()
        pytest.skip(f"MongoDB not reachable at {MONGO_URI}; skipping integration test")
    try:
        yield client[TEST_DB]
    finally:
        client.drop_database(TEST_DB)
        client.close()


def test_bulk_write_clean_and_idempotency(real_db):
    src, dst = real_db.raw, real_db.clean
    # 2500 records with batch_size 1000 -> 3 batched bulk_write calls.
    src.insert_many([{"_id": f"u{i}", "source_url": f"u{i}", "rating": "4,0"} for i in range(2500)])
    settings = CleanSettings(_env_file=None)

    first = clean_collection(src, dst, settings, skip_geocode=True)

    assert first.read == 2500
    assert first.written == 2500
    assert dst.count_documents({}) == 2500
    assert dst.find_one({"_id": "u0"})["rating"] == 4.0

    # Re-run converges to the same contents with no duplicates.
    second = clean_collection(src, dst, settings, skip_geocode=True)

    assert second.written == 2500
    assert dst.count_documents({}) == 2500
