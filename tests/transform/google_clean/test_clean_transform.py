"""Tests for the Google clean orchestration (mongomock).

mongomock cannot execute bulk_write (the default writer), so these inject the serial
writer, which produces identical collection state.
"""

from functools import partial

import mongomock
import pytest
from pydantic import ValidationError

from transform.google_clean.config import CleanSettings
from transform.google_clean.transform import clean_collection, serial_upsert

_clean = partial(clean_collection, writer=serial_upsert)

_ADDRESS_COMPONENTS = [
    {"longText": "2", "shortText": "2", "types": ["street_number"]},
    {"longText": "Via Osculati", "shortText": "Via Osculati", "types": ["route"]},
    {"longText": "Milano", "shortText": "Milano", "types": ["locality"]},
    {
        "longText": "Città metropolitana di Milano",
        "shortText": "MI",
        "types": ["administrative_area_level_2"],
    },
    {"longText": "Italy", "shortText": "IT", "types": ["country"]},
    {"longText": "20161", "shortText": "20161", "types": ["postal_code"]},
]


def _settings(**overrides):
    return CleanSettings(_env_file=None, **overrides)


@pytest.fixture
def db():
    return mongomock.MongoClient()["dataman"]


def _restaurant(place_id, name="DA MARIO", primary_type="italian_restaurant", **det):
    details = {
        "rating": 4.3,
        "userRatingCount": 200,
        "businessStatus": "OPERATIONAL",
        "addressComponents": _ADDRESS_COMPONENTS,
        "photos": [{}, {}],
    }
    details.update(det)
    return {
        "place_id": place_id,
        "name": name,
        "formatted_address": "Via Osculati, 2, 20161 Milano MI, Italy",
        "city": "Milan",
        "latitude": 45.51,
        "longitude": 9.16,
        "types": [primary_type, "food"],
        "primary_type": primary_type,
        "rating": 4.2,
        "user_rating_count": 201,
        "details": details,
    }


def _seed(coll, records):
    for rec in records:
        doc = dict(rec)
        doc.setdefault("_id", doc.get("place_id"))
        coll.insert_one(doc)


def test_happy_path_lean_normalized(db):
    src, dst = db.raw, db.clean
    _seed(src, [_restaurant("p1")])
    report = _clean(src, dst, _settings())

    assert report.read == 1
    assert report.written == 1
    doc = dst.find_one({"_id": "p1"})
    assert doc["name"] == "Da Mario"  # recased
    assert doc["city"] == "Milano"  # canonicalized
    assert doc["latitude"] == 45.51  # authoritative, copied
    assert doc["rating"] == 4.3 and doc["review_count"] == 200  # from details.*
    assert doc["category_tier"] == "restaurant" and doc["is_dining"] is True
    assert doc["photo_count"] == 2
    assert doc["postal_code"] == "20161" and doc["province"] == "MI"
    assert "details" not in doc  # heavy blob projected out
    assert doc["_source_collection"] == "restaurants_raw_google"


def test_idempotent(db):
    src, dst = db.raw, db.clean
    _seed(src, [_restaurant("p1"), _restaurant("p2", name="Bar Atlantic", primary_type="bar")])
    first = _clean(src, dst, _settings())
    second = _clean(src, dst, _settings())
    assert first.written == second.written == 2
    assert dst.count_documents({}) == 2


def test_drops_inert_junk_by_default(db):
    src, dst = db.raw, db.clean
    junk = _restaurant("junk1", name="Metropolitan City of Milan", primary_type="food_court")
    junk["details"] = {"businessStatus": "OPERATIONAL", "addressComponents": _ADDRESS_COMPONENTS}
    junk["rating"] = None  # inert: no rating in details *or* top-level
    junk["user_rating_count"] = None
    # no rating in details -> has_rating False, name geographic -> dropped
    _seed(src, [_restaurant("p1"), junk])
    report = _clean(src, dst, _settings())
    assert report.dropped_junk == 1
    assert report.written == 1
    assert dst.find_one({"_id": "junk1"}) is None


def test_keep_junk_when_disabled(db):
    src, dst = db.raw, db.clean
    junk = _restaurant("junk1", name="Metropolitan City of Milan", primary_type="food_court")
    junk["details"] = {"businessStatus": "OPERATIONAL", "addressComponents": _ADDRESS_COMPONENTS}
    junk["rating"] = None  # inert: no rating in details *or* top-level
    junk["user_rating_count"] = None
    _seed(src, [junk])
    report = _clean(src, dst, _settings(drop_junk=False))
    assert report.dropped_junk == 0
    assert report.written == 1
    doc = dst.find_one({"_id": "junk1"})
    assert doc["name_is_geographic"] is True


def test_non_dining_kept_and_flagged_by_default(db):
    src, dst = db.raw, db.clean
    gas = _restaurant("gas1", name="Q8", primary_type="gas_station")
    _seed(src, [gas])
    report = _clean(src, dst, _settings())
    assert report.dropped_non_dining == 0
    assert report.tier_non_dining == 1
    doc = dst.find_one({"_id": "gas1"})
    assert doc["category_tier"] == "non_dining"
    assert "non_dining" in doc["flags"]


def test_drop_non_dining_flag(db):
    src, dst = db.raw, db.clean
    _seed(src, [_restaurant("p1"), _restaurant("gas1", name="Q8", primary_type="gas_station")])
    report = _clean(src, dst, _settings(drop_non_dining=True))
    assert report.dropped_non_dining == 1
    assert report.written == 1
    assert dst.find_one({"_id": "gas1"}) is None


def test_missing_key_skipped(db):
    src, dst = db.raw, db.clean
    bad = _restaurant("x")
    del bad["place_id"]
    bad.pop("_id", None)
    src.insert_one(bad)
    _seed(src, [_restaurant("p1")])
    report = _clean(src, dst, _settings())
    assert report.missing_key == 1
    assert report.written == 1


def test_report_city_canonicalization(db):
    src, dst = db.raw, db.clean
    _seed(src, [_restaurant("p1"), _restaurant("p2", name="Bar X", primary_type="bar")])
    report = _clean(src, dst, _settings())
    # both raw cities are "Milan" -> 1 distinct before, "Milano" -> 1 distinct after
    assert report.cities_canonicalized == 2
    assert report.distinct_cities_before == 1
    assert report.distinct_cities_after == 1


def test_reset_clears_destination(db):
    src, dst = db.raw, db.clean
    dst.insert_one({"_id": "stale", "name": "old"})
    _seed(src, [_restaurant("p1")])
    _clean(src, dst, _settings(), reset=True)
    assert dst.find_one({"_id": "stale"}) is None
    assert dst.count_documents({}) == 1


def test_rerun_drop_non_dining_removes_stale(db):
    # A previously-kept non_dining doc must be deleted when a later run drops non_dining.
    src, dst = db.raw, db.clean
    _seed(src, [_restaurant("p1"), _restaurant("gas1", name="Q8", primary_type="gas_station")])
    _clean(src, dst, _settings())
    assert dst.find_one({"_id": "gas1"}) is not None
    second = _clean(src, dst, _settings(drop_non_dining=True))
    assert dst.find_one({"_id": "gas1"}) is None
    assert second.dropped_non_dining == 1
    assert second.stale_deleted == 1
    assert dst.count_documents({}) == 1


def test_rerun_default_removes_previously_kept_junk(db):
    # --keep-junk run leaves a junk doc; the default run must delete it.
    src, dst = db.raw, db.clean
    junk = _restaurant("junk1", name="Metropolitan City of Milan", primary_type="food_court")
    junk["details"] = {"businessStatus": "OPERATIONAL", "addressComponents": _ADDRESS_COMPONENTS}
    junk["rating"] = None  # inert: no rating in details *or* top-level
    junk["user_rating_count"] = None
    _seed(src, [junk])
    _clean(src, dst, _settings(drop_junk=False))
    assert dst.find_one({"_id": "junk1"}) is not None
    second = _clean(src, dst, _settings())
    assert dst.find_one({"_id": "junk1"}) is None
    assert second.stale_deleted == 1


def test_full_run_deletes_vanished_source_records(db):
    # A venue removed from the raw source must not linger in the clean collection on a full
    # rerun (convergence beyond drop-rule changes).
    src, dst = db.raw, db.clean
    _seed(src, [_restaurant("p1"), _restaurant("p2", name="Bar X", primary_type="bar")])
    _clean(src, dst, _settings())
    assert dst.count_documents({}) == 2
    src.delete_one({"_id": "p2"})  # delisted upstream
    report = _clean(src, dst, _settings())
    assert dst.find_one({"_id": "p2"}) is None
    assert report.stale_deleted == 1
    assert set(d["_id"] for d in dst.find()) == {"p1"}


def test_limited_run_does_not_delete_unread_records(db):
    # A partial --limit run must not delete the records it didn't read.
    src, dst = db.raw, db.clean
    _seed(src, [_restaurant("p1"), _restaurant("p2", name="Bar X", primary_type="bar")])
    _clean(src, dst, _settings())
    report = _clean(src, dst, _settings(), limit=1)
    assert report.stale_deleted == 0
    assert dst.count_documents({}) == 2


def test_source_equals_destination_raises(db):
    settings = _settings(source_collection="same", destination_collection="same")
    with pytest.raises(ValueError):
        _clean(db.same, db.same, settings)


def test_settings_reject_invalid_values():
    with pytest.raises(ValidationError):
        CleanSettings(_env_file=None, batch_size=0)
    with pytest.raises(ValidationError):
        CleanSettings(_env_file=None, low_review_threshold=-1)


def test_settings_need_no_google_key():
    # Mirrors the load layer: settings build from DATAMAN_ env with no API key required.
    settings = CleanSettings(_env_file=None)
    assert settings.source_collection == "restaurants_raw_google"
    assert settings.destination_collection == "restaurants_clean_google"
