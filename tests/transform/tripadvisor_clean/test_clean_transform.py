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
    assert "cuisine_type" not in doc  # replaced by parsed `cuisines`
    assert doc["cuisines"] == []
    assert doc["restaurant_name"] == "Dop20"
    assert doc["latitude"] == 45.46 and doc["longitude"] == 9.19
    assert doc["has_coordinates"] is True
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


# --- rich fields, flags, convergence (parity) -----------------------------------------

_RICH_RAW = {
    "source_url": "https://www.tripadvisor.it/Restaurant_Review-g1-d99-Reviews-X.html",
    "restaurant_name": "  Da Mario ",
    "address": "Via Vela, 14, 20133 Milano Italia",
    "rating": "4,5",
    "total_review": "(1.234 recensioni)",
    "cuisine_type": "Italiana, Pizza",
    "price_range": "€€-€€€",
    "number_photo_uploaded": "380",
    "website": "https://da-mario.it",
    "phone_number": "+39 02 1234",
    "email": "info@da-mario.it",
    "working_days_hours": "Lunedì and 12.00-15.00 and 19.00-23.00",
    "review": [
        {
            "author": {"nickname": "u1", "number_of_contribution": "875"},
            "title": "Ottimo",
            "text": "BuonissimoScopri di più",
            "date_of_publication": "29 maggio 2026",
        }
    ],
}


def test_rich_fields_written_and_raw_fields_dropped(db):
    src, dst = db.raw, db.clean
    _seed(src, [_RICH_RAW])

    _clean(src, dst, _settings(), skip_geocode=True)

    doc = dst.find_one({"_id": _RICH_RAW["source_url"]})
    # Parsed rich fields present.
    assert doc["photo_count"] == 380
    assert doc["price_band"] == "€€-€€€" and doc["price_tier_level"] == 2
    assert doc["cuisines"] == ["Italiana", "Pizza"]
    assert doc["opening_hours"] == [
        {"day": "monday", "opens": "12:00", "closes": "15:00"},
        {"day": "monday", "opens": "19:00", "closes": "23:00"},
    ]
    assert doc["reviews"][0]["text"] == "Buonissimo" and doc["sample_size"] == 1
    assert doc["has_phone"] and doc["has_website"] and doc["has_email"]
    # Replaced raw fields are gone.
    for dead in (
        "number_photo_uploaded",
        "price_range",
        "cuisine_type",
        "working_days_hours",
        "review",
    ):
        assert dead not in doc


def test_report_counters_for_rich_fields_and_flags(db):
    src, dst = db.raw, db.clean
    _seed(src, [_RICH_RAW])

    report = _clean(src, dst, _settings(), skip_geocode=True)

    assert report.photo_count_parsed == 1
    assert report.price_parsed == 1
    assert report.cuisines_present == 1 and report.multi_cuisine == 1
    assert report.opening_hours_parsed == 1
    assert report.with_reviews == 1
    assert report.with_phone == 1 and report.with_website == 1 and report.with_email == 1
    assert report.with_rating == 1 and report.without_rating == 0
    assert report.missing_review_count == 0


def test_geocode_not_found_flagged(db):
    src, dst = db.raw, db.clean
    _seed(src, [{"source_url": "u1", "address": "Nowhere, Milano", "rating": "4,0"}])

    report = _clean(src, dst, _settings(), geocoder=_Geocoder(result=None))

    doc = dst.find_one({"_id": "u1"})
    assert doc["has_coordinates"] is False
    assert "geocode_not_found" in doc["flags"]
    assert "missing_coordinates" in doc["flags"]
    assert report.geocode_not_found == 1


def test_full_run_deletes_stale_destination_docs(db):
    src, dst = db.raw, db.clean
    _seed(src, [{"source_url": "u1", "rating": "4,0"}, {"source_url": "u2", "rating": "3,0"}])
    dst.insert_one({"_id": "ghost", "rating": 1.0})  # vanished upstream

    report = _clean(src, dst, _settings(), skip_geocode=True)  # full run (limit=None)

    assert report.stale_deleted == 1
    assert dst.find_one({"_id": "ghost"}) is None
    assert dst.count_documents({}) == 2


def test_limited_run_never_deletes(db):
    src, dst = db.raw, db.clean
    _seed(src, [{"source_url": "u1", "rating": "4,0"}, {"source_url": "u2", "rating": "3,0"}])
    dst.insert_one({"_id": "ghost", "rating": 1.0})

    report = _clean(src, dst, _settings(), skip_geocode=True, limit=1)

    assert report.stale_deleted == 0
    assert dst.find_one({"_id": "ghost"}) is not None  # untouched by a partial run


def test_source_destination_collision_raises(db):
    src = db.same
    settings = _settings(
        source_collection="restaurants_same", destination_collection="restaurants_same"
    )
    with pytest.raises(ValueError, match="must differ"):
        _clean(src, src, settings, skip_geocode=True)
