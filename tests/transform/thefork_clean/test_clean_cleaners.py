"""Unit tests for the pure TheFork cleaning/parsing functions (no Mongo/network)."""

from transform.thefork_clean.cleaners import (
    canonical_city,
    clean_record,
    extract_address_parts,
    extract_tf_id,
    has_discount,
    is_cuisine_address_leak,
    normalize_address,
    normalize_name,
    parse_avg_price_eur,
    parse_discount_pct,
    sample_avg_rating,
    slim_reviews,
    split_cuisines,
    tidy_opening_hours,
)

_HOURS_STRUCTURED = [
    {
        "@type": "OpeningHoursSpecification",
        "opens": "12:00",
        "closes": "15:00",
        "dayOfWeek": ["lunedì"],
    },
    {
        "@type": "OpeningHoursSpecification",
        "opens": "19:00",
        "closes": "23:00",
        "dayOfWeek": ["lunedì"],
    },
]
_HOURS_RAW = (
    '[{"@type": "OpeningHoursSpecification", "opens": "09:00", "closes": "18:00", '
    '"dayOfWeek": ["martedì"]}]'
)


class TestExtractTfId:
    def test_extracts_trailing_id(self):
        assert extract_tf_id("drinkiamo-bistrot-r801007") == "801007"

    def test_none_when_absent(self):
        assert extract_tf_id("no-id-here") is None
        assert extract_tf_id(None) is None


class TestNormalizeName:
    def test_recases_all_caps(self):
        assert normalize_name("RISTORANTE AL SICOMORO") == "Ristorante Al Sicomoro"

    def test_preserves_mixed_case(self):
        assert normalize_name("Drinkiamo Bistrot") == "Drinkiamo Bistrot"

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

    def test_blank_is_none(self):
        assert canonical_city("  ") is None
        assert canonical_city(None) is None


class TestNormalizeAddress:
    def test_strips_intl_cap_prefix(self):
        assert normalize_address("Via Tortona, 28, Milano, I-20144, Italia") == (
            "Via Tortona, 28, Milano, 20144, Italia"
        )

    def test_folds_english_milan_and_italy(self):
        assert normalize_address("Viale Abruzzi, 83, Milan, 20129, Italy") == (
            "Viale Abruzzi, 83, Milano, 20129, Italia"
        )

    def test_does_not_touch_milano(self):
        assert "Milano" in normalize_address("Via X, 1, Milano, 20100, Italia")

    def test_blank_is_none(self):
        assert normalize_address(None) is None


class TestExtractAddressParts:
    def test_street_house_number_and_postal(self):
        parts = extract_address_parts("Via Imperia, 13, Milano, 20142, Italia")
        assert parts["street"] == "Via Imperia"
        assert parts["house_number"] == "13"  # civic number preserved, not dropped
        assert parts["postal_code"] == "20142"

    def test_house_number_with_letter_or_range(self):
        assert (
            extract_address_parts("Via Lazzaro Palazzi, 7/9, Milano, 20124, Italia")["house_number"]
            == "7/9"
        )

    def test_missing_civic_number(self):
        parts = extract_address_parts("Via Edmondo de Amicis, Milano")
        assert parts["postal_code"] is None
        assert parts["street"] == "Via Edmondo de Amicis"
        assert parts["house_number"] is None  # second chunk is not a civic number

    def test_empty(self):
        assert extract_address_parts(None) == {
            "street": None,
            "house_number": None,
            "postal_code": None,
        }


class TestParseAvgPriceEur:
    def test_parses_euro_string(self):
        assert parse_avg_price_eur("30 €") == 30

    def test_parses_outlier(self):
        assert parse_avg_price_eur("1 €") == 1

    def test_none_and_junk(self):
        assert parse_avg_price_eur(None) is None
        assert parse_avg_price_eur("€") is None


class TestDiscount:
    def test_has_discount(self):
        assert has_discount("sconto -20%") is True
        assert has_discount(None) is False
        assert has_discount("   ") is False

    def test_clean_patterns(self):
        assert parse_discount_pct("sconto -20%") == 20
        assert parse_discount_pct("Sconti fino al 30%") == 30
        assert parse_discount_pct("sconto del 30 %") == 30
        assert parse_discount_pct("sconto (20%") == 20

    def test_review_bleed_is_noise(self):
        # newline, over-long, or multiple distinct percentages -> not a real promo
        assert parse_discount_pct("sconto del\\n50%") is None
        assert (
            parse_discount_pct("sconto the fork. 111 euro in due senza vino e con il 50%") is None
        )
        assert parse_discount_pct("sconto del 20% sul cibo anziché del 30%") is None

    def test_none(self):
        assert parse_discount_pct(None) is None


class TestSplitCuisines:
    def test_splits_and_lifts_dietary(self):
        cuisines, dietary = split_cuisines("Piatti vegetariani, Italiano, Europeo")
        assert cuisines == ["Italiano", "Europeo"]
        assert dietary == ["vegetarian"]

    def test_drops_noise_token(self):
        cuisines, dietary = split_cuisines("Italiano, Solo in Italiano")
        assert cuisines == ["Italiano"]
        assert dietary == []

    def test_atomic_single_value(self):
        # the new scraper emits a single cuisine for most records
        assert split_cuisines("Americano") == (["Americano"], [])

    def test_dedup_and_multiple_dietary(self):
        cuisines, dietary = split_cuisines(
            "Italiano, Italiano, Piatti vegani, Opzioni senza glutine"
        )
        assert cuisines == ["Italiano"]
        assert dietary == ["vegan", "gluten_free"]

    def test_none(self):
        assert split_cuisines(None) == ([], [])


class TestCuisineAddressLeak:
    def test_detects_address_in_cuisine_field(self):
        # a real upstream leak from the dataset
        assert is_cuisine_address_leak("Corso Garibaldi, 111, Milano") is True

    def test_detects_cap_or_street_prefix(self):
        assert is_cuisine_address_leak("Via Roma 5") is True
        assert is_cuisine_address_leak("Qualcosa, 20100") is True

    def test_real_cuisines_not_flagged(self):
        for ok in ("Italiano", "Milanese", "Cucina locale", "Di Pesce", "Lombardo"):
            assert is_cuisine_address_leak(ok) is False
        assert is_cuisine_address_leak(None) is False


class TestTidyOpeningHours:
    def test_prefers_structured_and_maps_days(self):
        hours = tidy_opening_hours(_HOURS_STRUCTURED, None)
        assert hours == [
            {"day": "monday", "opens": "12:00", "closes": "15:00"},
            {"day": "monday", "opens": "19:00", "closes": "23:00"},
        ]

    def test_falls_back_to_raw_string(self):
        hours = tidy_opening_hours(None, _HOURS_RAW)
        assert hours == [{"day": "tuesday", "opens": "09:00", "closes": "18:00"}]

    def test_empty_when_both_absent(self):
        assert tidy_opening_hours(None, None) == []
        assert tidy_opening_hours([], "") == []

    def test_malformed_raw_string(self):
        assert tidy_opening_hours(None, "not json") == []

    def test_folds_past_midnight_close_to_valid_time(self):
        # "26:00" is not a valid clock time -> fold to "02:00" next day
        spec = [{"opens": "08:00", "closes": "26:00", "dayOfWeek": ["domenica"]}]
        assert tidy_opening_hours(spec, None) == [
            {"day": "sunday", "opens": "08:00", "closes": "02:00", "closes_next_day": True}
        ]

    def test_folds_midnight_and_various_late_hours(self):
        for raw_close, expected in [("24:00", "00:00"), ("24:30", "00:30"), ("29:00", "05:00")]:
            spec = [{"opens": "19:00", "closes": raw_close, "dayOfWeek": ["lunedì"]}]
            out = tidy_opening_hours(spec, None)
            assert out[0]["closes"] == expected and out[0]["closes_next_day"] is True

    def test_normal_hours_have_no_next_day_marker(self):
        spec = [{"opens": "12:00", "closes": "23:00", "dayOfWeek": ["lunedì"]}]
        assert tidy_opening_hours(spec, None) == [
            {"day": "monday", "opens": "12:00", "closes": "23:00"}
        ]


class TestSlimReviews:
    def _reviews(self, n):
        return [
            {
                "author_name": f"A{i}",
                "rating": 9.0,
                "title": None,
                "text": f"t{i}",
                "date": "2026-01-01",
            }
            for i in range(n)
        ]

    def test_drops_title_keeps_fields(self):
        out = slim_reviews(self._reviews(1))
        assert out == [{"author_name": "A0", "rating": 9.0, "text": "t0", "date": "2026-01-01"}]

    def test_caps_at_15(self):
        assert len(slim_reviews(self._reviews(20))) == 15

    def test_custom_cap(self):
        assert len(slim_reviews(self._reviews(20), cap=5)) == 5

    def test_non_list(self):
        assert slim_reviews(None) == []


class TestSampleAvgRating:
    def test_mean(self):
        reviews = [{"rating": 8.0}, {"rating": 10.0}]
        assert sample_avg_rating(reviews) == 9.0

    def test_ignores_non_numeric(self):
        assert sample_avg_rating([{"rating": None}, {"rating": 6.0}]) == 6.0

    def test_none_when_no_ratings(self):
        assert sample_avg_rating([{"rating": None}]) is None
        assert sample_avg_rating([]) is None


class TestCleanRecord:
    def _raw(self, **overrides):
        raw = {
            "source": "thefork",
            "source_id": "drinkiamo-bistrot-r801007",
            "restaurant_name": "DRINKIAMO BISTROT",
            "address": "Via Imperia, 13, Milano, I-20142, Italia",
            "city": "Milan",
            "latitude": 45.45,
            "longitude": 9.17,
            "rating": 9.4,
            "review_count": 1088,
            "cuisine_type": "Piatti vegetariani, Americano",
            "price_range": "15 €",
            "discount": "Sconti fino al 30%",
            "photo_count": 12,
            "website": None,
            "phone_number": None,
            "email": None,
            "working_days_hours": None,
            "working_hours_structured": _HOURS_STRUCTURED,
            "social_links": {},
            "restaurant_url": "https://www.thefork.it/ristorante/drinkiamo-bistrot-r801007",
            "review_snippets": ["Ottimo!"],
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

    def test_full_clean_doc(self):
        doc = clean_record(self._raw())
        assert doc["tf_id"] == "801007"
        assert doc["restaurant_name"] == "Drinkiamo Bistrot"  # recased
        assert doc["city"] == "Milano"  # canonicalized
        assert doc["street"] == "Via Imperia" and doc["postal_code"] == "20142"
        assert doc["house_number"] == "13"  # civic number preserved
        assert doc["rating"] == 9.4  # native 0-10, copied
        assert doc["avg_price_eur"] == 15
        assert doc["discount_pct"] == 30 and doc["has_discount"] is True
        assert doc["cuisines"] == ["Americano"] and doc["dietary_options"] == ["vegetarian"]
        assert doc["opening_hours"][0] == {"day": "monday", "opens": "12:00", "closes": "15:00"}
        assert doc["has_hours"] is True
        assert doc["review_snippets"] == ["Ottimo!"]  # passthrough
        assert doc["sample_size"] == 1

    def test_dead_fields_dropped(self):
        doc = clean_record(self._raw())
        for dead in (
            "phone_number",
            "email",
            "website",
            "social_links",
            "working_days_hours",
            "price_range",
            "discount",
            "cuisine_type",
        ):
            assert dead not in doc

    def test_reviews_slimmed_no_title(self):
        doc = clean_record(self._raw())
        assert "title" not in doc["reviews"][0]

    def test_flags_low_review_and_no_rating(self):
        doc = clean_record(self._raw(rating=None, review_count=3), low_review_threshold=10)
        assert doc["has_rating"] is False
        assert doc["low_review"] is True
        assert "no_rating" in doc["flags"] and "low_review" in doc["flags"]

    def test_rating_sample_divergent(self):
        # platform rating 9.4 vs sample mean 4.0 -> divergent
        doc = clean_record(
            self._raw(
                reviews=[{"author_name": "X", "rating": 4.0, "text": "t", "date": "2026-01-01"}]
            )
        )
        assert doc["rating_sample_divergent"] is True
        assert "rating_sample_divergent" in doc["flags"]

    def test_no_rating_backfill_from_reviews(self):
        # rating is null and must STAY null even though reviews carry ratings (biased sample)
        doc = clean_record(self._raw(rating=None))
        assert doc["rating"] is None
        assert doc["sample_avg_rating"] is not None  # sample feature still computed

    def test_cuisine_address_leak_rejected_and_flagged(self):
        # real dataset row: an address landed in cuisine_type
        doc = clean_record(self._raw(cuisine_type="Corso Garibaldi, 111, Milano"))
        assert doc["cuisines"] == [] and doc["dietary_options"] == []
        assert "invalid_cuisine_type" in doc["flags"]

    def test_missing_review_count_flagged(self):
        doc = clean_record(self._raw(review_count=None))
        assert doc["has_review_count"] is False
        assert doc["low_review"] is False  # missing != low
        assert "missing_review_count" in doc["flags"]

    def test_house_number_carried_into_doc(self):
        # the dominant address shape must keep the civic number out of the report's blind spot
        doc = clean_record(self._raw(address="Via Montebello, 7, Milano, 20121, Italia"))
        assert doc["street"] == "Via Montebello" and doc["house_number"] == "7"
