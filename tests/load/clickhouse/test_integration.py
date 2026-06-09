"""Integration tests that run against real MongoDB + ClickHouse.

These tests auto-skip when either backend is unreachable, so the suite stays
green without Docker.

Run them explicitly after starting both services::

    docker compose up -d mongo
    docker compose --profile analytics up -d clickhouse
    uv run pytest tests/load/clickhouse/test_integration.py
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

MONGO_URI = os.environ.get("DATAMAN_MONGO_URI", "mongodb://localhost:27017")
CH_HOST = os.environ.get("DATAMAN_CLICKHOUSE_HOST", "localhost")
CH_PORT = int(os.environ.get("DATAMAN_CLICKHOUSE_PORT", "8123"))
TEST_DB = "dataman_ch_load_it"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def real_mongo_collection():
    pymongo = pytest.importorskip("pymongo")
    from pymongo.errors import PyMongoError

    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
    try:
        client.admin.command("ping")
    except PyMongoError:
        client.close()
        pytest.skip(f"MongoDB not reachable at {MONGO_URI}")

    coll = client[TEST_DB]["restaurants_integrated_it"]
    coll.delete_many({})
    try:
        yield coll
    finally:
        client.drop_database(TEST_DB)
        client.close()


@pytest.fixture
def real_ch_client():
    clickhouse_connect = pytest.importorskip("clickhouse_connect")
    try:
        client = clickhouse_connect.get_client(
            host=CH_HOST,
            port=CH_PORT,
            username="default",
            password="",
        )
        client.command("SELECT 1")
    except Exception:  # noqa: BLE001
        pytest.skip(f"ClickHouse not reachable at {CH_HOST}:{CH_PORT}")

    # Use an isolated test database
    client.command(f"CREATE DATABASE IF NOT EXISTS {TEST_DB}")
    try:
        yield client
    finally:
        client.command(f"DROP DATABASE IF EXISTS {TEST_DB}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _doc(uid: str) -> dict:
    return {
        "_id": f"google:{uid}",
        "integrated_restaurant_id": f"google:{uid}",
        "canonical_name": f"Place {uid}",
        "canonical_address": "Via Test",
        "canonical_street": "Via Test",
        "canonical_house_number": "1",
        "canonical_postal_code": "20100",
        "canonical_city": "Milano",
        "latitude": 45.46,
        "longitude": 9.19,
        "coordinate_source": "google",
        "has_google": True,
        "has_tripadvisor": False,
        "has_thefork": False,
        "has_all_three_platforms": False,
        "platform_count": 1,
        "google_rating_5": 4.0,
        "tripadvisor_rating_5": None,
        "thefork_rating_raw_10": None,
        "thefork_rating_5": None,
        "rating_platform_count": 1,
        "rating_avg_5": 4.0,
        "rating_range_5": 0.0,
        "google_review_count": 10,
        "tripadvisor_review_count": None,
        "thefork_review_count": None,
        "website": "",
        "website_source": "",
        "website_match_status": "",
        "phone_match_status": "",
        "price_level": "moderate",
        "price_level_source": "google",
        "integration_flags": [],
        "_updated_at": datetime(2024, 6, 1, tzinfo=timezone.utc),
        "sources": {
            "google": {"ids": {"place_id": uid, "_id": uid}},
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_full_load_and_idempotency(real_mongo_collection, real_ch_client):
    from load.clickhouse.loader import load_target
    from load.clickhouse.projections import INTEGRATED_COLUMNS, project_integrated

    # Patch the spec to write to the isolated test DB table
    from load.clickhouse.schema import INTEGRATED_DDL
    from load.clickhouse.targets import TargetSpec

    spec = TargetSpec(
        name="integrated_it",
        mongo_collection=real_mongo_collection.name,
        table="restaurants_integrated_it",
        ddl=INTEGRATED_DDL.replace("restaurants_integrated", "restaurants_integrated_it"),
        projector=project_integrated,
        column_order=INTEGRATED_COLUMNS,
    )

    real_mongo_collection.insert_many([_doc(f"r{i}") for i in range(10)])

    # Override the client's database so DDL uses the test DB
    real_ch_client.database = TEST_DB

    first = load_target(spec, real_mongo_collection, real_ch_client)
    assert first.read == 10
    assert first.inserted == 10
    assert first.skipped == 0

    # Verify rows in ClickHouse
    count = real_ch_client.command(f"SELECT count() FROM {TEST_DB}.restaurants_integrated_it")
    assert int(count) == 10

    # Re-run: truncate + reload → same count, no duplicates
    second = load_target(spec, real_mongo_collection, real_ch_client)
    assert second.inserted == 10
    count2 = real_ch_client.command(f"SELECT count() FROM {TEST_DB}.restaurants_integrated_it")
    assert int(count2) == 10
