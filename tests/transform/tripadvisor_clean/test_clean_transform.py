"""Tests for the clean+geocode orchestration (mongomock; Nominatim stubbed).

mongomock cannot execute bulk_write (the default writer), so these inject the
serial writer, which produces identical collection state.
"""

from functools import partial

import mongomock
import pytest
from pydantic import ValidationError

from transform.tripadvisor_clean.config import CleanSettings
from transform.tripadvisor_clean.transform import (
    clean_collection,
    open_transform_collections,
    serial_upsert,
)

_clean = partial(clean_collection, writer=serial_upsert)


class _Loc:
    latitude = 45.46
    longitude = 9.19


class _Geocoder:
    """Returns a fixed location for every call (or None) and records call count."""

    def __init__(self, result=_Loc()):
        self._result = result
        self.calls = []

    def geocode(self, query, timeout=10):  # noqa: ARG002
        self.calls.append(query)
        return self._result


class _ExplodingGeocoder:
    def geocode(self, query, timeout=10):  # noqa: ARG002
        raise AssertionError("geocoder must not be called")


def _settings(**overrides):
    return CleanSettings(_env_file=None, delay_seconds=1.2, **overrides)


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    return client["dataman"]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("transform.tripadvisor_clean.transform.time.sleep", lambda _s: None)


def _seed(coll, records):
    for rec in records:
        doc = dict(rec)
        doc.setdefault("_id", doc.get("source_url"))
        coll.insert_one(doc)


def test_happy_path_typed_normalized_geocoded(db):
    src, dst = db.raw, db.clean
    _seed(
        src,
        [
            {
                "source_url": "u1",
                "restaurant_name": "  Dop20 ",
                "address": "Via Vincenzo Vela, 14, 20133 Milano Italia",
                "rating": "5,0",
                "total_review": "(0 recensioni)",
                "cuisine_type": "NaN",
            }
        ],
    )
    geocoder = _Geocoder()

    report = _clean(src, dst, _settings(), geocoder=geocoder)

    doc = dst.find_one({"_id": "u1"})
    assert doc["rating"] == 5.0
    assert doc["total_review"] == 0
    assert doc["cuisine_type"] is None
    assert doc["restaurant_name"] == "Dop20"
    assert doc["latitude"] == 45.46 and doc["longitude"] == 9.19
    assert report.read == 1 and report.written == 1 and report.geocode_found == 1
    assert report.ratings_parsed == 1 and report.reviews_parsed == 1


def test_idempotent_no_duplicates(db):
    src, dst = db.raw, db.clean
    _seed(src, [{"source_url": "u1", "address": "Piazza Duomo, Milano", "rating": "4,0"}])

    first = _clean(src, dst, _settings(), geocoder=_Geocoder())
    second = _clean(src, dst, _settings(), geocoder=_Geocoder())

    assert dst.count_documents({}) == 1
    assert first.geocode_found == 1
    # Second run resumes: already-geocoded record is not re-geocoded.
    assert second.geocode_skipped_done == 1
    assert second.geocode_found == 0


def test_resumability_skips_geocoder(db):
    src, dst = db.raw, db.clean
    _seed(src, [{"source_url": "u1", "address": "Piazza Duomo, Milano"}])
    dst.insert_one({"_id": "u1", "latitude": 1.0, "longitude": 2.0})

    report = _clean(src, dst, _settings(), geocoder=_ExplodingGeocoder())

    assert report.geocode_skipped_done == 1
    assert dst.find_one({"_id": "u1"})["latitude"] == 1.0  # preserved


def test_null_address_skipped_no_call(db):
    src, dst = db.raw, db.clean
    _seed(src, [{"source_url": "u1", "address": "NaN"}])

    report = _clean(src, dst, _settings(), geocoder=_ExplodingGeocoder())

    assert report.geocode_skipped_null_addr == 1
    doc = dst.find_one({"_id": "u1"})
    assert doc["latitude"] is None and doc["longitude"] is None


def test_skip_geocode_makes_no_calls_and_preserves_coords(db):
    src, dst = db.raw, db.clean
    _seed(src, [{"source_url": "u1", "address": "Piazza Duomo, Milano", "rating": "3,0"}])
    dst.insert_one({"_id": "u1", "latitude": 7.0, "longitude": 8.0})

    report = _clean(src, dst, _settings(), skip_geocode=True, geocoder=_ExplodingGeocoder())

    doc = dst.find_one({"_id": "u1"})
    assert doc["rating"] == 3.0  # cleaned/updated
    assert doc["latitude"] == 7.0 and doc["longitude"] == 8.0  # untouched
    assert report.geocode_found == 0 and report.geocode_skipped_done == 0


def test_duplicate_source_url_collapses(db):
    src, dst = db.raw, db.clean
    _seed(
        src,
        [
            {"_id": "a", "source_url": "dup", "rating": "4,0"},
            {"_id": "b", "source_url": "dup", "rating": "5,0"},
        ],
    )

    report = _clean(src, dst, _settings(), skip_geocode=True)

    assert dst.count_documents({}) == 1
    assert report.duplicates_collapsed == 1
    assert report.written == 1  # distinct docs, not raw rows
    assert dst.find_one({"_id": "dup"})["rating"] == 5.0  # last write wins


def test_missing_key_skipped(db):
    src, dst = db.raw, db.clean
    _seed(src, [{"source_url": "u1", "rating": "4,0"}])
    src.insert_one({"_id": "nokey", "rating": "3,0"})  # no source_url field

    report = _clean(src, dst, _settings(), skip_geocode=True)

    assert report.missing_key == 1
    assert dst.count_documents({}) == 1


def test_low_review_counted_not_removed(db):
    src, dst = db.raw, db.clean
    _seed(
        src,
        [
            {"source_url": "u1", "total_review": "(2 recensioni)"},
            {"source_url": "u2", "total_review": "(50 recensioni)"},
        ],
    )

    report = _clean(src, dst, _settings(low_review_threshold=10), skip_geocode=True)

    assert report.low_review == 1
    assert dst.count_documents({}) == 2  # both kept


def test_open_transform_collections_pings(monkeypatch):
    monkeypatch.setattr("pymongo.MongoClient", mongomock.MongoClient)

    client, src, dst = open_transform_collections(_settings())

    assert src.name == "restaurants_raw_tripadvisor"
    assert dst.name == "restaurants_clean_tripadvisor"
    client.close()


def test_sub_second_delay_rejected_at_settings_level():
    # env (DATAMAN_DELAY_SECONDS) must not be able to bypass the Nominatim policy.
    with pytest.raises(ValidationError):
        CleanSettings(_env_file=None, delay_seconds=0.5)


def test_missing_geocoder_fails_fast(db):
    src, dst = db.raw, db.clean
    _seed(src, [{"source_url": "u1", "address": "Piazza Duomo, Milano"}])

    # skip_geocode False but no geocoder wired -> caller bug, not a geocode miss.
    with pytest.raises(ValueError, match="geocoder is required"):
        _clean(src, dst, _settings())


def test_partial_coords_are_regeocoded(db):
    src, dst = db.raw, db.clean
    _seed(src, [{"source_url": "u1", "address": "Piazza Duomo, Milano"}])
    dst.insert_one({"_id": "u1", "latitude": 1.0, "longitude": None})  # corrupt/partial

    report = _clean(src, dst, _settings(), geocoder=_Geocoder())

    assert report.geocode_found == 1
    assert report.geocode_skipped_done == 0
    doc = dst.find_one({"_id": "u1"})
    assert doc["latitude"] == 45.46 and doc["longitude"] == 9.19
