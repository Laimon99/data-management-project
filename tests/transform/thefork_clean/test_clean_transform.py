"""Tests for the TheFork clean orchestration (mongomock).

mongomock cannot execute bulk_write (the default writer), so these inject the serial
writer, which produces identical collection state.
"""

from functools import partial

import mongomock
import pytest
from pydantic import ValidationError

from transform.thefork_clean.config import CleanSettings
from transform.thefork_clean.transform import clean_collection, serial_upsert

_clean = partial(clean_collection, writer=serial_upsert)

_HOURS_STRUCTURED = [
    {
        "@type": "OpeningHoursSpecification",
        "opens": "12:00",
        "closes": "15:00",
        "dayOfWeek": ["lunedì"],
    },
]


def _settings(**overrides):
    return CleanSettings(_env_file=None, **overrides)


@pytest.fixture
def db():
    return mongomock.MongoClient()["dataman"]


def _restaurant(source_id, name="DA MARIO", **overrides):
    raw = {
        "source": "thefork",
        "source_id": source_id,
        "restaurant_name": name,
        "address": "Via Imperia, 13, Milano, I-20142, Italia",
        "city": "Milan",
        "latitude": 45.45,
        "longitude": 9.17,
        "rating": 9.2,
        "review_count": 500,
        "cuisine_type": "Italiano",
        "price_range": "30 €",
        "discount": "sconto -20%",
        "photo_count": 10,
        "website": None,
        "phone_number": None,
        "email": None,
        "working_days_hours": None,
        "working_hours_structured": _HOURS_STRUCTURED,
        "social_links": {},
        "restaurant_url": f"https://www.thefork.it/ristorante/{source_id}",
        "review_snippets": ["Top"],
        "reviews": [
            {
                "author_name": "Max",
                "rating": 9.0,
                "title": None,
                "text": "buono",
                "date": "2026-05-26",
            }
        ],
        "scraped_at": "2026-06-04T14:00:00Z",
        "source_page_number": 1,
        "detail_scraped": True,
    }
    raw.update(overrides)
    return raw


def _seed(coll, records):
    for rec in records:
        doc = dict(rec)
        doc.setdefault("_id", doc.get("source_id"))
        coll.insert_one(doc)


def test_happy_path_lean_structured(db):
    src, dst = db.raw, db.clean
    _seed(src, [_restaurant("da-mario-r1")])
    report = _clean(src, dst, _settings())

    assert report.read == 1 and report.written == 1
    doc = dst.find_one({"_id": "da-mario-r1"})
    assert doc["tf_id"] == "1"
    assert doc["restaurant_name"] == "Da Mario"  # recased
    assert doc["city"] == "Milano"  # canonicalized
    assert doc["latitude"] == 45.45  # authoritative, copied
    assert doc["rating"] == 9.2  # native 0-10
    assert doc["avg_price_eur"] == 30
    assert doc["discount_pct"] == 20
    assert doc["opening_hours"][0] == {"day": "monday", "opens": "12:00", "closes": "15:00"}
    assert doc["postal_code"] == "20142"  # I- prefix stripped
    assert doc["_source_collection"] == "restaurants_raw_thefork"


def test_dead_fields_dropped_and_snippets_passthrough(db):
    src, dst = db.raw, db.clean
    _seed(src, [_restaurant("x-r1")])
    _clean(src, dst, _settings())
    doc = dst.find_one({"_id": "x-r1"})
    for dead in ("phone_number", "email", "website", "social_links", "price_range", "discount"):
        assert dead not in doc
    assert doc["review_snippets"] == ["Top"]  # kept as-is
    assert "title" not in doc["reviews"][0]  # reviews slimmed


def test_idempotent(db):
    src, dst = db.raw, db.clean
    _seed(src, [_restaurant("a-r1"), _restaurant("b-r2", name="Bar X")])
    first = _clean(src, dst, _settings())
    second = _clean(src, dst, _settings())
    assert first.written == second.written == 2
    assert dst.count_documents({}) == 2


def test_discount_noise_dropped_but_flagged_present(db):
    src, dst = db.raw, db.clean
    _seed(src, [_restaurant("n-r1", discount="sconto del 20% sul cibo anziché del 30%")])
    report = _clean(src, dst, _settings())
    doc = dst.find_one({"_id": "n-r1"})
    assert doc["has_discount"] is True
    assert doc["discount_pct"] is None
    assert report.discount_present == 1 and report.discount_noise_dropped == 1


def test_report_counters(db):
    src, dst = db.raw, db.clean
    rated = _restaurant("r-r1")
    unrated = _restaurant("u-r2", name="Nuovo", rating=None, review_count=2, reviews=[])
    _seed(src, [rated, unrated])
    report = _clean(src, dst, _settings())
    assert report.with_rating == 1 and report.without_rating == 1
    assert report.low_review == 1  # the unrated one has review_count 2 < 10
    assert report.avg_price_parsed == 2
    assert report.opening_hours_parsed == 2
    assert report.names_normalized == 1  # only "DA MARIO" recased; "Nuovo" already clean
    # address counters are not inflated by postal-code-only parsing
    assert report.postal_code_parsed == 2 and report.house_number_parsed == 2


def test_missing_key_skipped(db):
    src, dst = db.raw, db.clean
    bad = _restaurant("x")
    del bad["source_id"]
    bad.pop("_id", None)
    src.insert_one(bad)
    _seed(src, [_restaurant("ok-r1")])
    report = _clean(src, dst, _settings())
    assert report.missing_key == 1 and report.written == 1


def test_reset_clears_destination(db):
    src, dst = db.raw, db.clean
    dst.insert_one({"_id": "stale", "name": "old"})
    _seed(src, [_restaurant("p-r1")])
    _clean(src, dst, _settings(), reset=True)
    assert dst.find_one({"_id": "stale"}) is None
    assert dst.count_documents({}) == 1


def test_full_run_syncs_deleted_venues(db):
    # raw set changes (old {old, shared} -> new {shared, new}); a full rerun WITHOUT --reset
    # must converge to the current raw key set, deleting the delisted venue.
    src, dst = db.raw, db.clean
    _seed(src, [_restaurant("old-r1"), _restaurant("shared-r2")])
    _clean(src, dst, _settings())
    assert set(d["_id"] for d in dst.find()) == {"old-r1", "shared-r2"}

    src.delete_one({"_id": "old-r1"})  # venue delisted upstream
    src.insert_one({**_restaurant("new-r3"), "_id": "new-r3"})
    report = _clean(src, dst, _settings())
    assert set(d["_id"] for d in dst.find()) == {"shared-r2", "new-r3"}
    assert report.stale_deleted == 1


def test_limited_run_does_not_sync_delete(db):
    # a partial --limit run is intentionally incomplete and must NOT delete unread venues
    src, dst = db.raw, db.clean
    _seed(src, [_restaurant("a-r1"), _restaurant("b-r2"), _restaurant("c-r3")])
    _clean(src, dst, _settings())
    report = _clean(src, dst, _settings(), limit=1)
    assert report.stale_deleted == 0
    assert dst.count_documents({}) == 3


def test_source_equals_destination_raises(db):
    settings = _settings(source_collection="same", destination_collection="same")
    with pytest.raises(ValueError):
        _clean(db.same, db.same, settings)


def test_settings_reject_invalid_values():
    with pytest.raises(ValidationError):
        CleanSettings(_env_file=None, batch_size=0)
    with pytest.raises(ValidationError):
        CleanSettings(_env_file=None, low_review_threshold=-1)
    with pytest.raises(ValidationError):
        CleanSettings(_env_file=None, review_cap=0)


def test_settings_need_no_secrets():
    settings = CleanSettings(_env_file=None)
    assert settings.source_collection == "restaurants_raw_thefork"
    assert settings.destination_collection == "restaurants_clean_thefork"
