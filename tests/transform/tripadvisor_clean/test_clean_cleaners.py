"""Unit tests for the pure cleaning functions (no Mongo, no network)."""

import pytest

from transform.tripadvisor_clean.cleaners import (
    clean_record,
    extract_address_parts,
    extract_location_id,
    nan_to_none,
    normalize_address,
    normalize_name,
    parse_rating,
    parse_review_count,
)


@pytest.mark.parametrize(
    "value,expected",
    [("5,0", 5.0), ("4,5", 4.5), ("5.0", 5.0), (5, 5.0), (4.5, 4.5)],
)
def test_parse_rating_ok(value, expected):
    assert parse_rating(value) == expected


@pytest.mark.parametrize("value", ["NaN", None, "abc", "", "9,9", "6,0", -1])
def test_parse_rating_none(value):
    assert parse_rating(value) is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("(0 recensioni)", 0),
        ("(1 recensione)", 1),
        ("(1.234 recensioni)", 1234),
        ("(12 recensioni)", 12),
        (7, 7),
    ],
)
def test_parse_review_count_ok(value, expected):
    assert parse_review_count(value) == expected


@pytest.mark.parametrize("value", ["NaN", None, "(recensioni)", ""])
def test_parse_review_count_none(value):
    assert parse_review_count(value) is None


@pytest.mark.parametrize(
    "value,expected",
    [("NaN", None), ("nan", None), (" NaN ", None), ("", None), (None, None), ("ok", "ok")],
)
def test_nan_to_none(value, expected):
    assert nan_to_none(value) == expected


def test_normalize_name_collapses_whitespace():
    assert normalize_name("  Da   Mario  ") == "Da Mario"
    assert normalize_name("   ") is None
    assert normalize_name("NaN") is None


def test_normalize_address_standardizes_separators():
    assert normalize_address("Via Vela,14,  20133  Milano") == "Via Vela, 14, 20133 Milano"
    assert normalize_address("NaN") is None


def test_extract_address_parts_full():
    parts = extract_address_parts("Via Vincenzo Vela, 14, 20133 Milano Italia")
    assert parts == {
        "postal_code": "20133",
        "street": "Via Vincenzo Vela, 14",
        "city": "Milano",
    }


def test_extract_address_parts_no_cap():
    parts = extract_address_parts("Via Roma, Milano")
    assert parts["postal_code"] is None
    assert parts["street"] == "Via Roma"


def test_extract_address_parts_nan():
    assert extract_address_parts("NaN") == {"postal_code": None, "street": None, "city": None}


def test_extract_location_id():
    url = "https://www.tripadvisor.it/Restaurant_Review-g187849-d28119476-Reviews-Dop20-Milan.html"
    assert extract_location_id(url) == "28119476"
    assert extract_location_id("https://example.com/no-token") is None
    assert extract_location_id("NaN") is None
    assert extract_location_id(None) is None


def test_clean_record_typed_and_normalized():
    raw = {
        "source_url": "https://www.tripadvisor.it/Restaurant_Review-g187849-d28119476-Reviews-X.html",
        "restaurant_name": "  Dop20 ",
        "address": "Via Vincenzo Vela, 14, 20133 Milano Italia",
        "rating": "5,0",
        "total_review": "(0 recensioni)",
        "cuisine_type": "NaN",
        "phone_number": "+39 320",
    }
    out = clean_record(raw)

    assert out["restaurant_name"] == "Dop20"
    assert out["rating"] == 5.0
    assert out["total_review"] == 0
    assert out["cuisine_type"] is None  # NaN sentinel coerced
    assert out["phone_number"] == "+39 320"  # real value preserved
    assert out["postal_code"] == "20133"
    assert out["street"] == "Via Vincenzo Vela, 14"
    assert out["city"] == "Milano"
    assert out["ta_location_id"] == "28119476"
    assert "NaN" not in out.values()
