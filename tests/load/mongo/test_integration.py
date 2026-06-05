"""Integration tests that run against a real MongoDB.

These cover the default batched ``bulk_write`` path in :func:`load.mongo.loader.load_source`,
which mongomock 4.3.0 cannot execute. They connect to the MongoDB from
``DATAMAN_MONGO_URI`` (default ``mongodb://localhost:27017``) and **auto-skip** when no
server is reachable, so the suite stays green without Docker.

Run them explicitly with::

    docker compose up -d mongo
    uv run pytest tests/load/mongo/test_integration.py
"""

from __future__ import annotations

import json
import os

import pytest

from load.mongo.loader import load_source
from load.mongo.sources import SourceSpec

pymongo = pytest.importorskip("pymongo")
from pymongo.errors import PyMongoError  # noqa: E402

MONGO_URI = os.environ.get("DATAMAN_MONGO_URI", "mongodb://localhost:27017")
TEST_DB = "dataman_load_it"


@pytest.fixture
def real_collection():
    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
    try:
        client.admin.command("ping")
    except PyMongoError:
        client.close()
        pytest.skip(f"MongoDB not reachable at {MONGO_URI}; skipping integration test")
    coll = client[TEST_DB]["bulk_write_it"]
    coll.delete_many({})
    try:
        yield coll
    finally:
        client.drop_database(TEST_DB)
        client.close()


def _array_spec(path, collection_name) -> SourceSpec:
    return SourceSpec(
        name="thefork",
        raw_file=path,
        fmt="json_array",
        key_field="source_id",
        collection=collection_name,
    )


def test_bulk_write_load_and_idempotency(real_collection, tmp_path):
    # 2500 records with batch_size 1000 -> 3 batched bulk_write calls.
    path = tmp_path / "tf.json"
    path.write_text(
        json.dumps([{"source_id": f"id{i}", "n": i} for i in range(2500)]),
        encoding="utf-8",
    )
    spec = _array_spec(path, real_collection.name)

    first = load_source(spec, real_collection, batch_size=1000)

    assert first.read == 2500
    assert first.inserted == 2500
    assert first.modified == 0
    assert real_collection.count_documents({}) == 2500

    doc = real_collection.find_one({"_id": "id0"})
    assert doc["_id"] == "id0"
    assert doc["n"] == 0
    assert "_loaded_at" in doc
    assert doc["_source_file"] == str(path)

    # Re-run: idempotent, replaces rather than inserts (no duplicates).
    second = load_source(spec, real_collection, batch_size=1000)

    assert second.inserted == 0
    assert second.modified == 2500
    assert real_collection.count_documents({}) == 2500


def test_bulk_write_reset(real_collection, tmp_path):
    real_collection.insert_one({"_id": "stale"})
    path = tmp_path / "tf.json"
    path.write_text(json.dumps([{"source_id": "keep"}]), encoding="utf-8")
    spec = _array_spec(path, real_collection.name)

    load_source(spec, real_collection, reset=True)

    assert real_collection.count_documents({}) == 1
    assert real_collection.find_one({"_id": "stale"}) is None
    assert real_collection.find_one({"_id": "keep"}) is not None
