"""Unit tests for load.clickhouse.projections.

Pure function tests — no I/O, no DB connections.
"""

from datetime import datetime, timezone

import pytest

from load.clickhouse.projections import (
    project_clean_google,
    project_clean_thefork,
    project_clean_tripadvisor,
    project_integrated,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _integrated_doc(**overrides):
    base = {
        "_id": "google:ChIJabc",
        "integrated_restaurant_id": "google:ChIJabc",
        "canonical_name": "Pizzeria da Mario",
        "canonical_address": "Via Roma 1, Milano",
        "canonical_street": "Via Roma",
        "canonical_house_number": "1",
        "canonical_postal_code": "20100",
        "canonical_city": "Milano",
        "latitude": 45.46,
        "longitude": 9.19,
        "coordinate_source": "google",
        "has_google": True,
        "has_tripadvisor": True,
        "has_thefork": False,
        "has_all_three_platforms": False,
        "platform_count": 2,
        "google_rating_5": 4.5,
        "tripadvisor_rating_5": 4.3,
        "thefork_rating_raw_10": None,
        "thefork_rating_5": None,
        "rating_platform_count": 2,
        "rating_avg_5": 4.4,
        "rating_range_5": 0.2,
        "google_review_count": 120,
        "tripadvisor_review_count": 80,
        "thefork_review_count": None,
        "website": "https://pizza.it",
        "website_source": "google",
        "website_match_status": "exact_match",
        "phone_match_status": "match",
        "price_level": "moderate",
        "price_level_source": "google",
        "integration_flags": [],
        "_updated_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "sources": {
            "google": {"ids": {"place_id": "ChIJabc", "_id": "ChIJabc"}},
            "tripadvisor": {"ids": {"source_url": "https://ta.com/r1", "_id": "https://ta.com/r1"}},
        },
    }
    base.update(overrides)
    return base


def _google_doc(**overrides):
    base = {
        "_id": "ChIJxyz",
        "place_id": "ChIJxyz",
        "name": "Osteria della Piazza",
        "latitude": 45.47,
        "longitude": 9.20,
        "address": "Piazza Duomo 5",
        "street": "Piazza Duomo",
        "house_number": "5",
        "postal_code": "20122",
        "locality": "Milano",
        "province": "MI",
        "country": "IT",
        "city": "Milano",
        "city_out_of_area": False,
        "rating": 4.2,
        "review_count": 300,
        "has_rating": True,
        "low_review": False,
        "primary_type": "restaurant",
        "types": ["restaurant", "food"],
        "category_tier": "restaurant",
        "is_dining": True,
        "is_operational": True,
        "business_status": "OPERATIONAL",
        "photo_count": 20,
        "price_level": "PRICE_LEVEL_MODERATE",
        "has_website": True,
        "has_phone": True,
        "website": "https://osteria.it",
        "phone": "+39 02 1234567",
        "flags": [],
    }
    base.update(overrides)
    return base


def _tripadvisor_doc(**overrides):
    base = {
        "_id": "https://ta.com/r2",
        "source_url": "https://ta.com/r2",
        "ta_location_id": "7654321",
        "restaurant_name": "Trattoria Milanese",
        "rating": 4.0,
        "total_review": 150,
        "address": "Via Torino 10",
        "street": "Via Torino",
        "house_number": "10",
        "postal_code": "20123",
        "city": "Milano",
        "latitude": 45.46,
        "longitude": 9.18,
        "has_coordinates": True,
        "photo_count": 15,
        "price_band": "€€",
        "price_tier_level": 2,
        "cuisines": ["Italian", "Milanese"],
        "has_rating": True,
        "has_review_count": True,
        "low_review": False,
        "has_address": True,
        "has_reviews": True,
        "has_hours": True,
        "has_phone": False,
        "has_website": False,
        "has_email": False,
        "website": "",
        "phone": "",
        "email": "",
        "flags": [],
    }
    base.update(overrides)
    return base


def _thefork_doc(**overrides):
    base = {
        "_id": "thefork-r123",
        "source_id": "thefork-r123",
        "source": "thefork",
        "tf_id": "r123",
        "restaurant_url": "https://thefork.it/r123",
        "restaurant_name": "Ristorante Bello",
        "latitude": 45.45,
        "longitude": 9.17,
        "address": "Via Brera 3",
        "street": "Via Brera",
        "house_number": "3",
        "postal_code": "20121",
        "city": "Milano",
        "rating": 8.5,
        "review_count": 200,
        "has_rating": True,
        "has_review_count": True,
        "low_review": False,
        "avg_price_eur": 35,
        "discount_pct": None,
        "has_discount": False,
        "cuisines": ["Italian"],
        "dietary_options": ["vegetarian"],
        "has_hours": True,
        "photo_count": 10,
        "has_reviews": True,
        "sample_size": 15,
        "sample_avg_rating": 8.4,
        "rating_sample_divergent": False,
        "flags": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# project_integrated
# ---------------------------------------------------------------------------


def test_integrated_happy_path():
    row = project_integrated(_integrated_doc())
    assert row is not None
    assert row["integrated_restaurant_id"] == "google:ChIJabc"
    assert row["google_place_id"] == "ChIJabc"
    assert row["tripadvisor_source_url"] == "https://ta.com/r1"
    assert row["thefork_source_id"] == ""  # not in sources
    assert row["has_google"] == 1
    assert row["has_tripadvisor"] == 1
    assert row["has_thefork"] == 0
    assert row["has_all_three_platforms"] == 0
    assert row["google_rating_5"] == 4.5
    assert row["thefork_rating_raw_10"] is None
    assert row["rating_range_5"] == pytest.approx(0.2)
    assert row["price_level"] == "moderate"
    assert row["integration_flags"] == []
    assert isinstance(row["updated_at"], datetime)


def test_integrated_projects_per_platform_features():
    doc = _integrated_doc(
        sources={
            "google": {
                "ids": {"place_id": "ChIJabc"},
                "photo_count": 10,
                "contacts": {"website": "https://g.it", "phone": "+39 02 1"},
                "price": {"price_level": "PRICE_LEVEL_MODERATE"},
                "classification": {"category_tier": "restaurant", "is_dining": True},
            },
            "tripadvisor": {
                "ids": {"source_url": "https://ta.com/r1"},
                "photo_count": 2730,
                "contacts": {"website": "https://ta.it", "email": "x@y.it"},
                "price": {"price_band": "€€-€€€", "price_tier_level": 2},
                "cuisines": ["Italiana", "Pizza"],
            },
            "thefork": {
                "ids": {"source_id": "tf:99"},
                "photo_count": 43,
                "price": {"avg_price_eur": 25},
                "cuisines": ["Di Carne"],
            },
        }
    )
    row = project_integrated(doc)
    assert row is not None
    assert row["google_photo_count"] == 10
    assert row["tripadvisor_photo_count"] == 2730
    assert row["thefork_photo_count"] == 43
    assert row["google_has_website"] == 1
    assert row["google_has_phone"] == 1
    assert row["tripadvisor_has_website"] == 1
    assert row["tripadvisor_has_phone"] == 0  # absent in contacts
    assert row["tripadvisor_has_email"] == 1
    assert row["tripadvisor_cuisines"] == ["Italiana", "Pizza"]
    assert row["thefork_cuisines"] == ["Di Carne"]
    assert row["primary_cuisine"] == "Italiana"  # Tripadvisor preferred
    assert row["google_price_level"] == "PRICE_LEVEL_MODERATE"
    assert row["tripadvisor_price_band"] == "€€-€€€"
    assert row["tripadvisor_price_tier_level"] == 2
    assert row["thefork_avg_price_eur"] == 25
    assert row["price_tier"] == 2  # Tripadvisor tier preferred
    assert row["google_category_tier"] == "restaurant"
    assert row["google_is_dining"] == 1


def test_integrated_per_platform_features_default_when_absent():
    doc = _integrated_doc()
    doc["sources"] = {}
    row = project_integrated(doc)
    assert row is not None
    assert row["google_photo_count"] is None
    assert row["tripadvisor_has_website"] == 0
    assert row["tripadvisor_cuisines"] == []
    assert row["primary_cuisine"] == ""
    assert row["price_tier"] is None
    assert row["google_is_dining"] == 0


def test_integrated_price_tier_falls_back_to_google_then_thefork():
    google_only = _integrated_doc(
        sources={"google": {"price": {"price_level": "PRICE_LEVEL_EXPENSIVE"}}}
    )
    assert project_integrated(google_only)["price_tier"] == 3

    thefork_only = _integrated_doc(sources={"thefork": {"price": {"avg_price_eur": 60}}})
    assert project_integrated(thefork_only)["price_tier"] == 4

    thefork_cheap = _integrated_doc(sources={"thefork": {"price": {"avg_price_eur": 12}}})
    assert project_integrated(thefork_cheap)["price_tier"] == 1


def test_integrated_price_level_list_coercion():
    doc = _integrated_doc(price_level=["moderate", "expensive"], price_level_source="tie")
    row = project_integrated(doc)
    assert row is not None
    assert row["price_level"] == "moderate / expensive"


def test_integrated_missing_key_returns_none():
    doc = _integrated_doc()
    del doc["integrated_restaurant_id"]
    assert project_integrated(doc) is None


def test_integrated_empty_key_returns_none():
    assert project_integrated(_integrated_doc(integrated_restaurant_id="")) is None
    assert project_integrated(_integrated_doc(integrated_restaurant_id="   ")) is None


def test_integrated_absent_source_blocks_give_empty_join_keys():
    doc = _integrated_doc()
    doc["sources"] = {}  # no platform blocks at all
    row = project_integrated(doc)
    assert row is not None
    assert row["google_place_id"] == ""
    assert row["tripadvisor_source_url"] == ""
    assert row["thefork_source_id"] == ""


def test_integrated_missing_updated_at_uses_fallback():
    doc = _integrated_doc()
    del doc["_updated_at"]
    row = project_integrated(doc)
    assert row is not None
    assert isinstance(row["updated_at"], datetime)


def test_integrated_missing_arrays_become_empty():
    doc = _integrated_doc(integration_flags=None)
    row = project_integrated(doc)
    assert row is not None
    assert row["integration_flags"] == []


# ---------------------------------------------------------------------------
# project_clean_google
# ---------------------------------------------------------------------------


def test_clean_google_happy_path():
    row = project_clean_google(_google_doc())
    assert row is not None
    assert row["place_id"] == "ChIJxyz"
    assert row["name"] == "Osteria della Piazza"
    assert row["is_dining"] == 1
    assert row["is_operational"] == 1
    assert row["city_out_of_area"] == 0
    assert row["types"] == ["restaurant", "food"]
    assert row["flags"] == []


def test_clean_google_missing_key_returns_none():
    doc = _google_doc()
    del doc["place_id"]
    assert project_clean_google(doc) is None


def test_clean_google_null_fields_pass_through():
    row = project_clean_google(_google_doc(rating=None, review_count=None))
    assert row is not None
    assert row["rating"] is None
    assert row["review_count"] is None


def test_clean_google_missing_types_becomes_empty_list():
    row = project_clean_google(_google_doc(types=None))
    assert row is not None
    assert row["types"] == []


# ---------------------------------------------------------------------------
# project_clean_tripadvisor
# ---------------------------------------------------------------------------


def test_clean_tripadvisor_happy_path():
    row = project_clean_tripadvisor(_tripadvisor_doc())
    assert row is not None
    assert row["source_url"] == "https://ta.com/r2"
    assert row["ta_location_id"] == "7654321"
    assert row["has_coordinates"] == 1
    assert row["cuisines"] == ["Italian", "Milanese"]
    assert row["price_tier_level"] == 2


def test_clean_tripadvisor_missing_key_returns_none():
    doc = _tripadvisor_doc()
    del doc["source_url"]
    assert project_clean_tripadvisor(doc) is None


def test_clean_tripadvisor_null_rating_passes_through():
    row = project_clean_tripadvisor(_tripadvisor_doc(rating=None))
    assert row is not None
    assert row["rating"] is None


def test_clean_tripadvisor_missing_cuisines_becomes_empty():
    row = project_clean_tripadvisor(_tripadvisor_doc(cuisines=None))
    assert row is not None
    assert row["cuisines"] == []


# ---------------------------------------------------------------------------
# project_clean_thefork
# ---------------------------------------------------------------------------


def test_clean_thefork_happy_path():
    row = project_clean_thefork(_thefork_doc())
    assert row is not None
    assert row["source_id"] == "thefork-r123"
    assert row["tf_id"] == "r123"
    assert row["rating"] == pytest.approx(8.5)
    assert row["cuisines"] == ["Italian"]
    assert row["dietary_options"] == ["vegetarian"]
    assert row["rating_sample_divergent"] == 0
    assert row["has_discount"] == 0


def test_clean_thefork_missing_key_returns_none():
    doc = _thefork_doc()
    del doc["source_id"]
    assert project_clean_thefork(doc) is None


def test_clean_thefork_null_nullable_fields_pass_through():
    row = project_clean_thefork(_thefork_doc(avg_price_eur=None, discount_pct=None))
    assert row is not None
    assert row["avg_price_eur"] is None
    assert row["discount_pct"] is None


def test_clean_thefork_missing_arrays_become_empty():
    row = project_clean_thefork(_thefork_doc(cuisines=None, dietary_options=None, flags=None))
    assert row is not None
    assert row["cuisines"] == []
    assert row["dietary_options"] == []
    assert row["flags"] == []
