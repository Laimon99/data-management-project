"""Focused tests for ER-prep schema homogenization across clean transforms."""

import pytest

from transform.common.contacts import normalize_phone, normalize_website
from transform.google_clean.cleaners import clean_record as clean_google_record
from transform.tripadvisor_clean.cleaners import clean_record as clean_tripadvisor_record


@pytest.mark.parametrize(
    "value,expected",
    [
        ("+39 02 645 6224", "+39026456224"),
        ("02 1234567", "+39021234567"),
        ("+39 02-123.4567", "+39021234567"),
        (None, None),
        ("NaN", None),
    ],
)
def test_phone_normalization(value, expected):
    assert normalize_phone(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://www.example.it/", "example.it"),
        ("http://example.it", "example.it"),
        ("example.it", "example.it"),
        (None, None),
        ("NaN", None),
    ],
)
def test_website_normalization(value, expected):
    assert normalize_website(value) == expected


def test_google_house_number_and_canonical_contacts():
    doc = clean_google_record(
        {
            "place_id": "g1",
            "name": "Da Mario",
            "formatted_address": "Via Roma, 12/A, 20121 Milano MI, Italy",
            "city": "Milan",
            "latitude": 45.0,
            "longitude": 9.0,
            "primary_type": "italian_restaurant",
            "types": ["italian_restaurant", "restaurant"],
            "details": {
                "addressComponents": [
                    {"longText": "12/A", "types": ["street_number"]},
                    {"longText": "Via Roma", "types": ["route"]},
                    {"longText": "Milano", "types": ["locality"]},
                    {"longText": "20121", "types": ["postal_code"]},
                ],
                "internationalPhoneNumber": "+39 02 645 6224",
                "websiteUri": "https://www.example.it/",
            },
        }
    )

    assert doc["house_number"] == "12/A"
    assert "street_number" not in doc
    assert doc["phone"] == "+39026456224"
    assert doc["website"] == "example.it"


def test_tripadvisor_house_number_and_canonical_contacts():
    doc = clean_tripadvisor_record(
        {
            "source_url": "https://www.tripadvisor.it/Restaurant_Review-g1-d99-Reviews-X.html",
            "restaurant_name": "X",
            "address": "Via Pastrengo 16 Il bistrot del Teatro Verdi, 20159 Milano Italia",
            "phone_number": "02 1234567",
            "website": "http://www.example.it/",
        }
    )

    assert doc["street"] == "Via Pastrengo"
    assert doc["house_number"] == "16"
    assert doc["phone"] == "+39021234567"
    assert doc["website"] == "example.it"
    assert "phone_number" not in doc
