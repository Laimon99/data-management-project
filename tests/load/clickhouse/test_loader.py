"""Unit tests for load.clickhouse.loader.

Uses mongomock for the Mongo source and a FakeClickHouseClient for the
destination so no real databases are required.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

import mongomock
import pytest
from pymongo.errors import ServerSelectionTimeoutError

from load.clickhouse.config import ClickHouseLoaderSettings
from load.clickhouse.loader import load_target, open_clickhouse, open_mongo
from load.clickhouse.targets import TARGETS

# ---------------------------------------------------------------------------
# Fake ClickHouse client
# ---------------------------------------------------------------------------


class FakeClickHouseClient:
    """Minimal stand-in for a clickhouse_connect client.

    Records every INSERT so tests can inspect the rows that would have been sent.
    Also records DDL / TRUNCATE commands so tests can assert idempotency logic.
    """

    def __init__(self, database: str = "dataman") -> None:
        self.database = database
        self.commands: list[str] = []
        self.inserts: list[tuple[str, list[list[Any]], list[str]]] = []

    def command(self, sql: str, *args: Any, **kwargs: Any) -> None:
        self.commands.append(sql.strip())

    def insert(
        self,
        table: str,
        data: list[list[Any]],
        column_names: list[str] | None = None,
    ) -> None:
        self.inserts.append((table, data, column_names or []))


def _fake_writer(
    ch_client: FakeClickHouseClient,
    table: str,
    rows: list[dict[str, Any]],
    column_order: list[str],
) -> int:
    """Writer that delegates to FakeClickHouseClient.insert."""
    data = [[row[col] for col in column_order] for row in rows]
    ch_client.insert(table, data, column_names=column_order)
    return len(rows)


# ---------------------------------------------------------------------------
# Mongo helpers
# ---------------------------------------------------------------------------


def _mongo_collection(name: str = "test_coll") -> Any:
    client = mongomock.MongoClient()
    return client["dataman"][name]


# ---------------------------------------------------------------------------
# Integrated target fixtures
# ---------------------------------------------------------------------------


def _integrated_doc(place_id: str = "g1", ta_url: str = "", tf_id: str = "") -> dict:
    return {
        "_id": f"google:{place_id}",
        "integrated_restaurant_id": f"google:{place_id}",
        "canonical_name": f"Restaurant {place_id}",
        "canonical_address": "Via Test 1",
        "canonical_street": "Via Test",
        "canonical_house_number": "1",
        "canonical_postal_code": "20100",
        "canonical_city": "Milano",
        "latitude": 45.46,
        "longitude": 9.19,
        "coordinate_source": "google",
        "has_google": True,
        "has_tripadvisor": bool(ta_url),
        "has_thefork": bool(tf_id),
        "has_all_three_platforms": False,
        "platform_count": 1 + bool(ta_url) + bool(tf_id),
        "google_rating_5": 4.0,
        "tripadvisor_rating_5": None,
        "thefork_rating_raw_10": None,
        "thefork_rating_5": None,
        "rating_platform_count": 1,
        "rating_avg_5": 4.0,
        "rating_range_5": 0.0,
        "google_review_count": 50,
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
            "google": {"ids": {"place_id": place_id, "_id": place_id}},
        },
    }


# ---------------------------------------------------------------------------
# Tests: load_target
# ---------------------------------------------------------------------------


def test_load_target_happy_path():
    spec = TARGETS["integrated"]
    coll = _mongo_collection(spec.mongo_collection)
    coll.insert_many([_integrated_doc("r1"), _integrated_doc("r2"), _integrated_doc("r3")])
    ch = FakeClickHouseClient()

    report = load_target(spec, coll, ch, writer=_fake_writer)

    assert report.read == 3
    assert report.inserted == 3
    assert report.skipped == 0
    # DDL was issued
    assert any("CREATE TABLE IF NOT EXISTS" in cmd for cmd in ch.commands)
    # TRUNCATE was issued
    assert any("TRUNCATE TABLE" in cmd for cmd in ch.commands)
    # Rows were inserted
    assert len(ch.inserts) >= 1
    total_rows = sum(len(insert[1]) for insert in ch.inserts)
    assert total_rows == 3


def test_load_target_skips_missing_key():
    spec = TARGETS["integrated"]
    coll = _mongo_collection(spec.mongo_collection)
    good = _integrated_doc("r1")
    bad = {**_integrated_doc("r2"), "integrated_restaurant_id": ""}
    coll.insert_many([good, bad])
    ch = FakeClickHouseClient()

    report = load_target(spec, coll, ch, writer=_fake_writer)

    assert report.read == 2
    assert report.inserted == 1
    assert report.skipped == 1
    assert report.skipped_reasons == {"missing_key": 1}


def test_load_target_truncate_and_reload_is_idempotent():
    """Running load_target twice gives the same row count (no duplicates)."""
    spec = TARGETS["integrated"]
    coll = _mongo_collection(spec.mongo_collection)
    coll.insert_many([_integrated_doc("r1"), _integrated_doc("r2")])
    ch = FakeClickHouseClient()

    first = load_target(spec, coll, ch, writer=_fake_writer)
    second = load_target(spec, coll, ch, writer=_fake_writer)

    # Both runs insert exactly 2 rows (TRUNCATE + fresh INSERT each time)
    assert first.inserted == 2
    assert second.inserted == 2
    # TRUNCATE was issued at least twice
    truncates = [cmd for cmd in ch.commands if "TRUNCATE TABLE" in cmd]
    assert len(truncates) >= 2


def test_load_target_empty_collection():
    spec = TARGETS["integrated"]
    coll = _mongo_collection(spec.mongo_collection)
    ch = FakeClickHouseClient()

    report = load_target(spec, coll, ch, writer=_fake_writer)

    assert report.read == 0
    assert report.inserted == 0
    assert report.skipped == 0


def test_load_target_batch_flushing():
    """Verify that rows are flushed in chunks; all rows arrive."""
    spec = TARGETS["integrated"]
    coll = _mongo_collection(spec.mongo_collection)
    coll.insert_many([_integrated_doc(f"r{i}") for i in range(25)])
    ch = FakeClickHouseClient()

    report = load_target(spec, coll, ch, writer=_fake_writer, batch_size=10)

    assert report.inserted == 25
    total_rows = sum(len(insert[1]) for insert in ch.inserts)
    assert total_rows == 25
    # 25 docs with batch_size=10 → 3 INSERT calls (10, 10, 5)
    assert len(ch.inserts) == 3


def test_load_target_clean_google():
    spec = TARGETS["clean_google"]
    coll = _mongo_collection(spec.mongo_collection)
    coll.insert_many(
        [
            {
                "_id": "gx1",
                "place_id": "gx1",
                "name": "Foo",
                "latitude": 45.0,
                "longitude": 9.0,
                "address": "Via A",
                "street": "Via A",
                "house_number": "1",
                "postal_code": "20100",
                "locality": "Milano",
                "province": "MI",
                "country": "IT",
                "city": "Milano",
                "city_out_of_area": False,
                "rating": 4.1,
                "review_count": 10,
                "has_rating": True,
                "low_review": False,
                "primary_type": "restaurant",
                "types": ["restaurant"],
                "category_tier": "restaurant",
                "is_dining": True,
                "is_operational": True,
                "business_status": "OPERATIONAL",
                "photo_count": 5,
                "price_level": "PRICE_LEVEL_MODERATE",
                "has_website": True,
                "has_phone": True,
                "website": "https://foo.it",
                "phone": "+39 02 999",
                "flags": [],
            }
        ]
    )
    ch = FakeClickHouseClient()

    report = load_target(spec, coll, ch, writer=_fake_writer)

    assert report.inserted == 1
    assert report.skipped == 0


def test_load_target_clean_tripadvisor():
    spec = TARGETS["clean_tripadvisor"]
    coll = _mongo_collection(spec.mongo_collection)
    coll.insert_one(
        {
            "_id": "https://ta.com/test",
            "source_url": "https://ta.com/test",
            "ta_location_id": "123",
            "restaurant_name": "Test TA",
            "rating": 4.2,
            "total_review": 50,
            "address": "Via B",
            "street": "Via B",
            "house_number": "2",
            "postal_code": "20121",
            "city": "Milano",
            "latitude": 45.47,
            "longitude": 9.18,
            "has_coordinates": True,
            "photo_count": 3,
            "price_band": "€€",
            "price_tier_level": 2,
            "cuisines": ["Italian"],
            "has_rating": True,
            "has_review_count": True,
            "low_review": False,
            "has_address": True,
            "has_reviews": True,
            "has_hours": False,
            "has_phone": False,
            "has_website": False,
            "has_email": False,
            "website": "",
            "phone": "",
            "email": "",
            "flags": [],
        }
    )
    ch = FakeClickHouseClient()

    report = load_target(spec, coll, ch, writer=_fake_writer)

    assert report.inserted == 1


def test_load_target_clean_thefork():
    spec = TARGETS["clean_thefork"]
    coll = _mongo_collection(spec.mongo_collection)
    coll.insert_one(
        {
            "_id": "tf-r1",
            "source_id": "tf-r1",
            "source": "thefork",
            "tf_id": "r1",
            "restaurant_url": "https://thefork.it/r1",
            "restaurant_name": "Test TF",
            "latitude": 45.45,
            "longitude": 9.17,
            "address": "Via C",
            "street": "Via C",
            "house_number": "3",
            "postal_code": "20122",
            "city": "Milano",
            "rating": 8.0,
            "review_count": 100,
            "has_rating": True,
            "has_review_count": True,
            "low_review": False,
            "avg_price_eur": 30,
            "discount_pct": None,
            "has_discount": False,
            "cuisines": ["Italian"],
            "dietary_options": [],
            "has_hours": True,
            "photo_count": 5,
            "has_reviews": True,
            "sample_size": 10,
            "sample_avg_rating": 7.9,
            "rating_sample_divergent": False,
            "flags": [],
        }
    )
    ch = FakeClickHouseClient()

    report = load_target(spec, coll, ch, writer=_fake_writer)

    assert report.inserted == 1


# ---------------------------------------------------------------------------
# Tests: open_mongo
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests: open_clickhouse
# ---------------------------------------------------------------------------


def test_open_clickhouse_bootstraps_database(monkeypatch):
    """open_clickhouse must create the destination DB before selecting it.

    A fresh ClickHouse volume has no ``dataman`` database; connecting with it
    selected raises UNKNOWN_DATABASE. This test fails if the loader ever goes
    back to passing ``database=`` at connect time without creating it first.
    """
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self) -> None:
            self.database: str | None = None
            self.commands: list[str] = []

        def command(self, sql: str, *args: Any, **kwargs: Any) -> None:
            self.commands.append(sql.strip())

    def _fake_get_client(**kwargs: Any) -> _FakeClient:
        captured["connect_kwargs"] = kwargs
        return _FakeClient()

    fake_module = type(sys)("clickhouse_connect")
    fake_module.get_client = _fake_get_client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "clickhouse_connect", fake_module)

    client = open_clickhouse(ClickHouseLoaderSettings(_env_file=None))

    # 1. Did NOT select a database at connect time (would raise on a fresh volume)
    assert "database" not in captured["connect_kwargs"]
    # 2. Bootstrapped the database, then selected it
    assert any(cmd == "CREATE DATABASE IF NOT EXISTS dataman" for cmd in client.commands)
    assert client.database == "dataman"


def test_open_mongo_returns_collection(monkeypatch):
    monkeypatch.setattr("pymongo.MongoClient", mongomock.MongoClient)

    client, coll = open_mongo(ClickHouseLoaderSettings(_env_file=None), "restaurants_integrated")

    assert coll.name == "restaurants_integrated"
    client.close()


def test_open_mongo_closes_on_ping_failure(monkeypatch):
    closed = {"value": False}

    class _Admin:
        def command(self, *args: Any, **kwargs: Any) -> None:
            raise ServerSelectionTimeoutError("no servers")

    class _Client:
        admin = _Admin()

        def close(self) -> None:
            closed["value"] = True

    monkeypatch.setattr("pymongo.MongoClient", lambda *a, **k: _Client())

    with pytest.raises(ServerSelectionTimeoutError):
        open_mongo(ClickHouseLoaderSettings(_env_file=None), "any_collection")
    assert closed["value"] is True
