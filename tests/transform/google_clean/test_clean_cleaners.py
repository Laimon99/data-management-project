"""Unit tests for the pure Google cleaning/classification functions (no Mongo/network)."""

from transform.google_clean.cleaners import (
    amenity_flags,
    canonical_city,
    classify_tier,
    clean_record,
    count_photos,
    extract_address_parts,
    is_city_out_of_area,
    is_dining,
    is_geographic_name,
    normalize_address,
    normalize_name,
    parse_price_range,
    slim_reviews,
)

_ADDRESS_COMPONENTS = [
    {"longText": "2", "shortText": "2", "types": ["street_number"]},
    {"longText": "Via Gaetano Osculati", "shortText": "Via Gaetano Osculati", "types": ["route"]},
    {"longText": "Milano", "shortText": "Milano", "types": ["locality", "political"]},
    {
        "longText": "Città metropolitana di Milano",
        "shortText": "MI",
        "types": ["administrative_area_level_2", "political"],
    },
    {"longText": "Italy", "shortText": "IT", "types": ["country", "political"]},
    {"longText": "20161", "shortText": "20161", "types": ["postal_code"]},
]


class TestNormalizeName:
    def test_recases_all_caps(self):
        assert normalize_name("IN PIAZZA") == "In Piazza"

    def test_preserves_mixed_case(self):
        assert normalize_name("Da Giovanni") == "Da Giovanni"

    def test_collapses_whitespace(self):
        assert normalize_name("  Bar   Atlantic ") == "Bar Atlantic"

    def test_blank_is_none(self):
        assert normalize_name("   ") is None
        assert normalize_name(None) is None


class TestCanonicalCity:
    def test_english_milan_becomes_italian(self):
        assert canonical_city("Milan") == "Milano"

    def test_milano_unchanged(self):
        assert canonical_city("Milano") == "Milano"

    def test_other_municipality_passthrough(self):
        assert canonical_city("Sesto San Giovanni") == "Sesto San Giovanni"

    def test_recases_all_caps(self):
        assert canonical_city("MARTINA FRANCA") == "Martina Franca"

    def test_blank_is_none(self):
        assert canonical_city(None) is None


class TestOutOfArea:
    def test_flags_far_city(self):
        assert is_city_out_of_area("Torino") is True
        assert is_city_out_of_area("Martina Franca") is True

    def test_milan_in_area(self):
        assert is_city_out_of_area("Milano") is False
        assert is_city_out_of_area(None) is False


class TestExtractAddressParts:
    def test_lifts_structured_parts(self):
        parts = extract_address_parts(_ADDRESS_COMPONENTS)
        assert parts["street"] == "Via Gaetano Osculati"
        assert parts["house_number"] == "2"
        assert parts["postal_code"] == "20161"
        assert parts["locality"] == "Milano"
        assert parts["province"] == "MI"
        assert parts["country"] == "Italy"

    def test_missing_components_are_none(self):
        parts = extract_address_parts([{"longText": "Italy", "types": ["country"]}])
        assert parts["country"] == "Italy"
        assert parts["postal_code"] is None
        assert parts["street"] is None

    def test_non_list_is_all_none(self):
        assert extract_address_parts(None)["locality"] is None


class TestClassifyTier:
    def test_restaurant_suffix(self):
        assert classify_tier("italian_restaurant") == "restaurant"

    def test_restaurant_extra(self):
        assert classify_tier("food_court") == "restaurant"
        assert classify_tier("bistro") == "restaurant"

    def test_cafe_bar_bakery(self):
        for pt in ("bar", "cafe", "bakery", "ice_cream_shop", "wine_bar"):
            assert classify_tier(pt) == "cafe_bar_bakery"

    def test_non_dining(self):
        for pt in ("gas_station", "supermarket", "hotel", "barber_shop"):
            assert classify_tier(pt) == "non_dining"

    def test_bar_and_grill(self):
        assert classify_tier("bar_and_grill") == "restaurant"

    def test_unknown_and_null(self):
        assert classify_tier(None) == "unknown"
        assert classify_tier("food") == "unknown"  # ambiguous primary, no restaurant type

    def test_types_fallback(self):
        assert classify_tier("food", ["restaurant", "food"]) == "restaurant"

    def test_non_dining_types_fallback(self):
        # null/ambiguous primary_type but a non-dining tag -> non_dining (not unknown)
        assert classify_tier(None, ["gas_station", "point_of_interest"]) == "non_dining"
        assert classify_tier("food", ["hotel", "lodging"]) == "non_dining"

    def test_dining_token_wins_over_non_dining_in_fallback(self):
        assert classify_tier(None, ["restaurant", "store"]) == "restaurant"

    def test_is_dining_helper(self):
        assert is_dining("restaurant") is True
        assert is_dining("cafe_bar_bakery") is True
        assert is_dining("non_dining") is False
        assert is_dining("unknown") is False


class TestTierVocabularyCoverage:
    """Guard against EDA-observed dining types silently drifting into `unknown`."""

    EXPECTED = {
        "italian_restaurant": "restaurant",
        "pizza_restaurant": "restaurant",
        "fast_food_restaurant": "restaurant",
        "sushi_restaurant": "restaurant",
        "steak_house": "restaurant",
        "food_court": "restaurant",
        "bistro": "restaurant",
        "bar_and_grill": "restaurant",
        "kebab_shop": "restaurant",
        "meal_takeaway": "restaurant",
        "ramen_restaurant": "restaurant",
        "bar": "cafe_bar_bakery",
        "cafe": "cafe_bar_bakery",
        "coffee_shop": "cafe_bar_bakery",
        "bakery": "cafe_bar_bakery",
        "pastry_shop": "cafe_bar_bakery",
        "cake_shop": "cafe_bar_bakery",
        "ice_cream_shop": "cafe_bar_bakery",
        "wine_bar": "cafe_bar_bakery",
        "cocktail_bar": "cafe_bar_bakery",
        "pub": "cafe_bar_bakery",
        "gas_station": "non_dining",
        "supermarket": "non_dining",
        "hotel": "non_dining",
        "store": "non_dining",
        "hypermarket": "non_dining",
        "pharmacy": "non_dining",
        "night_club": "non_dining",
    }

    def test_known_types_map_as_expected(self):
        for pt, tier in self.EXPECTED.items():
            assert classify_tier(pt) == tier, f"{pt} -> {classify_tier(pt)} (expected {tier})"


class TestGeographicName:
    def test_metropolitan_city(self):
        assert is_geographic_name("Metropolitan City of Milan") is True

    def test_bare_city(self):
        assert is_geographic_name("Milano") is True

    def test_equals_locality(self):
        assert is_geographic_name("Novate Milanese", "Novate Milanese") is True

    def test_real_name_false(self):
        assert is_geographic_name("Trattoria del Pescatore", "Milano") is False

    def test_bare_cap(self):
        assert is_geographic_name("20161") is True


class TestFeatures:
    def test_slim_reviews(self):
        raw = [
            {
                "rating": 5,
                "text": {"text": "Great", "languageCode": "en"},
                "authorAttribution": {"displayName": "Marco"},
                "publishTime": "2026-05-01T00:00:00Z",
                "flagContentUri": "drop-me",
            }
        ]
        out = slim_reviews(raw)
        assert out == [
            {
                "rating": 5,
                "text": "Great",
                "language": "en",
                "publish_time": "2026-05-01T00:00:00Z",
                "author": "Marco",
            }
        ]

    def test_slim_reviews_caps_at_five(self):
        assert len(slim_reviews([{"rating": 1}] * 9)) == 5

    def test_slim_reviews_non_list(self):
        assert slim_reviews(None) == []

    def test_count_photos(self):
        assert count_photos([{}, {}, {}]) == 3
        assert count_photos(None) == 0

    def test_parse_price_range(self):
        pr = {
            "startPrice": {"currencyCode": "EUR", "units": "10"},
            "endPrice": {"currencyCode": "EUR", "units": "20"},
        }
        assert parse_price_range(pr) == {"start": 10, "end": 20, "currency": "EUR"}
        assert parse_price_range(None) is None

    def test_amenity_flags_snake_cased(self):
        flags = amenity_flags({"dineIn": True, "servesVegetarianFood": False, "rating": 4.2})
        assert flags == {"dine_in": True, "serves_vegetarian_food": False}

    def test_amenity_flags_excludes_non_bool(self):
        flags = amenity_flags(
            {"dineIn": True, "takeout": None, "delivery": "yes", "reservable": False}
        )
        assert flags == {"dine_in": True, "reservable": False}


class TestNormalizeAddress:
    def test_collapses_and_separators(self):
        assert normalize_address("Via Roma,  2 , 20100  Milano") == "Via Roma, 2, 20100 Milano"


class TestCleanRecord:
    def _raw(self, **overrides):
        raw = {
            "place_id": "ChIJ_abc",
            "name": "IN PIAZZA",
            "formatted_address": "Via Gaetano Osculati, 2, 20161 Milano MI, Italy",
            "city": "Milan",
            "latitude": 45.5167,
            "longitude": 9.1692,
            "types": ["italian_restaurant", "restaurant", "food"],
            "primary_type": "italian_restaurant",
            "rating": 4.2,
            "user_rating_count": 549,
            "details": {
                "rating": 4.3,
                "userRatingCount": 548,
                "businessStatus": "OPERATIONAL",
                "priceLevel": "PRICE_LEVEL_INEXPENSIVE",
                "websiteUri": "https://x.example",
                "internationalPhoneNumber": "+39 02 1234567",
                "addressComponents": _ADDRESS_COMPONENTS,
                "photos": [{}, {}, {}],
                "dineIn": True,
                "reviews": [
                    {
                        "rating": 5,
                        "text": {"text": "Ottimo", "languageCode": "it"},
                        "authorAttribution": {"displayName": "Anna"},
                        "publishTime": "2026-05-02T00:00:00Z",
                    }
                ],
            },
        }
        raw.update(overrides)
        return raw

    def test_projection_and_normalization(self):
        doc = clean_record(self._raw())
        assert doc["name"] == "In Piazza"
        assert doc["city"] == "Milano"  # canonicalized from addressComponents locality
        assert doc["latitude"] == 45.5167 and doc["longitude"] == 9.1692
        assert doc["street"] == "Via Gaetano Osculati"
        assert doc["house_number"] == "2"
        assert "street_number" not in doc
        assert doc["postal_code"] == "20161"
        assert doc["province"] == "MI"
        assert doc["website"] == "x.example"
        assert doc["phone"] == "+39021234567"
        assert doc["category_tier"] == "restaurant"
        assert doc["is_dining"] is True
        assert doc["photo_count"] == 3
        assert doc["dine_in"] is True
        assert "details" not in doc  # heavy blob projected out

    def test_rating_from_details_not_toplevel(self):
        # details fetched later -> canonical
        doc = clean_record(self._raw())
        assert doc["rating"] == 4.3
        assert doc["review_count"] == 548

    def test_low_review_flag(self):
        doc = clean_record(
            self._raw(details={"rating": 4.0, "userRatingCount": 3}), low_review_threshold=10
        )
        assert doc["low_review"] is True
        assert "low_review" in doc["flags"]

    def test_no_rating(self):
        # no rating in details *or* top-level (the coalesce falls back to top-level)
        doc = clean_record(
            self._raw(
                rating=None,
                user_rating_count=None,
                details={"businessStatus": "OPERATIONAL"},
            )
        )
        assert doc["rating"] is None
        assert doc["has_rating"] is False
        assert doc["review_count"] is None

    def test_non_dining_flagged(self):
        doc = clean_record(self._raw(primary_type="gas_station", types=["gas_station"]))
        assert doc["category_tier"] == "non_dining"
        assert doc["is_dining"] is False
        assert "non_dining" in doc["flags"]

    def test_slimmed_reviews_present(self):
        doc = clean_record(self._raw())
        assert doc["reviews"][0]["author"] == "Anna"
        assert doc["reviews"][0]["language"] == "it"

    def test_rating_count_coalesce_to_toplevel(self):
        # details lacks rating/count but the top-level (seed) has them -> coalesce
        raw = self._raw(
            rating=4.0,
            user_rating_count=12,
            details={"businessStatus": "OPERATIONAL", "addressComponents": _ADDRESS_COMPONENTS},
        )
        doc = clean_record(raw)
        assert doc["rating"] == 4.0
        assert doc["review_count"] == 12
        assert doc["has_rating"] is True

    def test_float_review_count_accepted(self):
        raw = self._raw(
            details={
                "rating": 4.0,
                "userRatingCount": 200.0,  # whole-valued float
                "businessStatus": "OPERATIONAL",
                "addressComponents": _ADDRESS_COMPONENTS,
            }
        )
        assert clean_record(raw)["review_count"] == 200

    def test_low_review_is_count_only(self):
        # rating absent, count below threshold -> still low_review
        raw = self._raw(
            rating=None,
            user_rating_count=3,
            details={
                "userRatingCount": 3,
                "businessStatus": "OPERATIONAL",
                "addressComponents": _ADDRESS_COMPONENTS,
            },
        )
        doc = clean_record(raw, low_review_threshold=10)
        assert doc["has_rating"] is False
        assert doc["low_review"] is True
        assert "low_review" in doc["flags"]

    def test_low_review_false_when_count_missing(self):
        raw = self._raw(
            rating=None,
            user_rating_count=None,
            details={"businessStatus": "OPERATIONAL", "addressComponents": _ADDRESS_COMPONENTS},
        )
        doc = clean_record(raw)
        assert doc["review_count"] is None
        assert doc["low_review"] is False

    def test_blank_website_phone_not_present(self):
        raw = self._raw(
            details={
                "rating": 4.0,
                "userRatingCount": 50,
                "businessStatus": "OPERATIONAL",
                "addressComponents": _ADDRESS_COMPONENTS,
                "websiteUri": "   ",
                "internationalPhoneNumber": "",
            }
        )
        doc = clean_record(raw)
        assert doc["website"] is None and doc["has_website"] is False
        assert doc["phone"] is None and doc["has_phone"] is False
