"""Unit tests for the pure cleaning functions (no Mongo, no network)."""

import pytest

from transform.tripadvisor_clean.cleaners import (
    clean_record,
    extract_address_parts,
    extract_location_id,
    nan_to_none,
    normalize_address,
    normalize_name,
    parse_opening_hours,
    parse_photo_count,
    parse_price,
    parse_rating,
    parse_review_count,
    parse_review_date,
    slim_reviews,
    split_cuisines,
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
        "street": "Via Vincenzo Vela",
        "house_number": "14",
        "city": "Milano",
    }


def test_extract_address_parts_no_cap():
    parts = extract_address_parts("Via Roma, Milano")
    assert parts["postal_code"] is None
    assert parts["street"] == "Via Roma"
    assert parts["house_number"] is None


def test_extract_address_parts_nan():
    assert extract_address_parts("NaN") == {
        "postal_code": None,
        "street": None,
        "house_number": None,
        "city": None,
    }


@pytest.mark.parametrize(
    "address,street,house_number",
    [
        ("Via Carlo Pascal 6, 20133 Milano Italia", "Via Carlo Pascal", "6"),
        (
            "Via Pastrengo 16 Il bistrot del Teatro Verdi, 20159 Milano Italia",
            "Via Pastrengo",
            "16",
        ),
        ("Piazza del Duomo, 20121 Milano Italia", "Piazza del Duomo", None),
        ("Via Roma 12/A, 20121 Milano Italia", "Via Roma", "12/A"),
        ("Via XX Settembre 8, 20121 Milano Italia", "Via XX Settembre", "8"),
    ],
)
def test_extract_address_parts_street_house_number_split(address, street, house_number):
    parts = extract_address_parts(address)
    assert parts["street"] == street
    assert parts["house_number"] == house_number


def test_extract_location_id():
    url = "https://www.tripadvisor.it/Restaurant_Review-g187849-d28119476-Reviews-Dop20-Milan.html"
    assert extract_location_id(url) == "28119476"
    assert extract_location_id("https://example.com/no-token") is None
    assert extract_location_id("NaN") is None
    assert extract_location_id(None) is None


# --- rich-field parsers ---------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [("380", 380), ("1.234", 1234), (12, 12), ("0", 0)],
)
def test_parse_photo_count_ok(value, expected):
    assert parse_photo_count(value) == expected


@pytest.mark.parametrize("value", ["NaN", None, "", "abc", -1])
def test_parse_photo_count_none(value):
    assert parse_photo_count(value) is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("€", ("€", 1)),
        ("€€-€€€", ("€€-€€€", 2)),
        ("€€€€", ("€€€€", 4)),
    ],
)
def test_parse_price_ok(value, expected):
    assert parse_price(value) == expected


@pytest.mark.parametrize("value", ["NaN", None, "", "cheap", "$$"])
def test_parse_price_unknown(value):
    assert parse_price(value) == (None, None)


def test_split_cuisines_dedupes_and_trims():
    assert split_cuisines("Italiana, Pizza") == ["Italiana", "Pizza"]
    assert split_cuisines("  Italiana ,, italiana , Pizza ") == ["Italiana", "Pizza"]
    assert split_cuisines("Indiana") == ["Indiana"]


@pytest.mark.parametrize("value", ["NaN", None, "", 5])
def test_split_cuisines_empty(value):
    assert split_cuisines(value) == []


def test_parse_opening_hours_normal_and_closed():
    raw = (
        "Domenica: Chiuso and Lunedì and 2.00-10.30 and Martedì and 2.00-10.30 "
        "and Mercoledì and 2.00-10.30 and Giovedì and Chiuso and Venerdì and Chiuso "
        "and Sabato and Chiuso"
    )
    hours = parse_opening_hours(raw)
    # Closed days emit nothing; only the three open days survive.
    assert hours == [
        {"day": "monday", "opens": "02:00", "closes": "10:30"},
        {"day": "tuesday", "opens": "02:00", "closes": "10:30"},
        {"day": "wednesday", "opens": "02:00", "closes": "10:30"},
    ]


def test_parse_opening_hours_split_shift():
    raw = "Domenica: 12.00-15.00 and 19.00-23.00 and Lunedì and Chiuso"
    hours = parse_opening_hours(raw)
    assert hours == [
        {"day": "sunday", "opens": "12:00", "closes": "15:00"},
        {"day": "sunday", "opens": "19:00", "closes": "23:00"},
    ]


def test_parse_opening_hours_past_midnight():
    hours = parse_opening_hours("Sabato and 12.00-1.00")
    assert hours == [
        {"day": "saturday", "opens": "12:00", "closes": "01:00", "closes_next_day": True}
    ]


@pytest.mark.parametrize("value", ["NaN", None, "", "garbage with no day", 5])
def test_parse_opening_hours_empty_or_malformed(value):
    assert parse_opening_hours(value) == []


@pytest.mark.parametrize(
    "value,expected",
    [("29 maggio 2026", "2026-05-29"), ("8 aprile 2024", "2024-04-08")],
)
def test_parse_review_date_ok(value, expected):
    assert parse_review_date(value) == expected


@pytest.mark.parametrize("value", ["NaN", None, "", "29 foo 2026", "tomorrow"])
def test_parse_review_date_none(value):
    assert parse_review_date(value) is None


def test_slim_reviews_strips_read_more_and_caps():
    raw = [
        {
            "author": {"nickname": "user1", "number_of_contribution": "875"},
            "title": "Ottimo",
            "text": "Cibo buono e personaleScopri di più",
            "date_of_publication": "29 maggio 2026",
        },
        {
            "author": {"nickname": "user2", "number_of_contribution": "NaN"},
            "title": "NaN",
            "text": "Discreto",
            "date_of_publication": "NaN",
        },
    ]
    out = slim_reviews(raw, cap=1)
    assert len(out) == 1  # cap respected
    assert out[0] == {
        "nickname": "user1",
        "contributions": 875,
        "title": "Ottimo",
        "text": "Cibo buono e personale",  # read-more suffix removed
        "date": "2026-05-29",
    }


def test_slim_reviews_handles_nan_and_partial():
    assert slim_reviews("NaN") == []
    out = slim_reviews(
        [{"author": {"nickname": "u2", "number_of_contribution": "NaN"}, "text": "Discreto"}]
    )
    assert out[0]["contributions"] is None and out[0]["title"] is None
    assert out[0]["text"] == "Discreto" and out[0]["date"] is None


def test_clean_record_flags_and_has_fields():
    raw = {
        "source_url": "https://www.tripadvisor.it/Restaurant_Review-g1-d99-Reviews-X.html",
        "restaurant_name": "X",
        "address": "NaN",
        "rating": "4,0",
        "total_review": "(0 recensioni)",
        "cuisine_type": "Italiana, Pizza",
        "price_range": "€€-€€€",
        "number_photo_uploaded": "12",
        "website": "NaN",
        "phone_number": "+39 02 1234",
        "email": "NaN",
        "working_days_hours": "NaN",
        "review": "NaN",
    }
    out = clean_record(raw)

    assert out["cuisines"] == ["Italiana", "Pizza"]
    assert out["price_band"] == "€€-€€€" and out["price_tier_level"] == 2
    assert out["photo_count"] == 12
    assert out["opening_hours"] == [] and out["reviews"] == [] and out["sample_size"] == 0
    assert out["has_rating"] is True and out["has_review_count"] is True
    assert out["has_phone"] is True and out["has_website"] is False and out["has_email"] is False
    assert out["has_address"] is False and out["has_hours"] is False and out["has_reviews"] is False
    # zero reviews is below threshold (low_review) and a rating with 0 reviews; plus the
    # missing address and absent hours/reviews are all flagged (count-only, never dropped).
    assert set(out["flags"]) == {
        "missing_address",
        "low_review",
        "rating_with_zero_reviews",
        "no_reviews",
        "no_hours",
    }
    # geocode/coordinate flags are added by the transform layer, not the pure cleaner.
    assert "has_coordinates" not in out


def test_clean_record_typed_and_normalized():
    raw = {
        "source_url": (
            "https://www.tripadvisor.it/Restaurant_Review-g187849-d28119476-Reviews-X.html"
        ),
        "restaurant_name": "  Dop20 ",
        "address": "Via Vincenzo Vela, 14, 20133 Milano Italia",
        "rating": "5,0",
        "total_review": "(0 recensioni)",
        "cuisine_type": "NaN",
        "phone_number": "+39 320",
        "website": "https://www.dop20.it/",
    }
    out = clean_record(raw)

    assert out["restaurant_name"] == "Dop20"
    assert out["rating"] == 5.0
    assert out["total_review"] == 0
    assert "cuisine_type" not in out  # replaced by parsed `cuisines`
    assert out["cuisines"] == []  # NaN sentinel -> empty list
    assert out["phone"] == "+39320"
    assert out["website"] == "dop20.it"
    assert "phone_number" not in out
    assert out["postal_code"] == "20133"
    assert out["street"] == "Via Vincenzo Vela"
    assert out["house_number"] == "14"
    assert out["city"] == "Milano"
    assert out["ta_location_id"] == "28119476"
    assert "NaN" not in out.values()
