"""Pure cleaning / classification functions for raw Google Places records.

No MongoDB, no network, no file I/O — every function takes and returns plain Python
values, so they are unit-testable in isolation. The strict EDA
(``services/extract/google_places_api/eda-report.md``) established that Google data is
already typed, valid, and geocoded, so this module does **projection + normalization +
relevance flagging**, not type-repair or geocoding.
"""

from __future__ import annotations

import re
from typing import Any

from transform.common.contacts import normalize_phone, normalize_website

_WS_RE = re.compile(r"\s+")

# --- dining-relevance vocabulary (curated from the seed's 175 distinct primary_types) ---
# In scope: `restaurant` and `cafe_bar_bakery`. Out of scope (noise): `non_dining`.
RESTAURANT_EXTRA = {
    "restaurant",
    "bistro",
    "diner",
    "gastropub",
    "brewpub",
    "food_court",
    "steak_house",
    "meal_takeaway",
    "meal_delivery",
    "pizza_delivery",
    "buffet_restaurant",
    "kebab_shop",
    "noodle_shop",
    "hot_dog_stand",
    "fast_food",
    "bar_and_grill",
}
CAFE_BAR_BAKERY = {
    "bar",
    "cafe",
    "coffee_shop",
    "coffee_roastery",
    "internet_cafe",
    "dog_cafe",
    "coffee_stand",
    "bakery",
    "pastry_shop",
    "cake_shop",
    "confectionery",
    "chocolate_shop",
    "donut_shop",
    "bagel_shop",
    "dessert_shop",
    "ice_cream_shop",
    "juice_shop",
    "acai_shop",
    "salad_shop",
    "snack_bar",
    "deli",
    "sandwich_shop",
    "wine_bar",
    "cocktail_bar",
    "pub",
    "irish_pub",
    "sports_bar",
    "lounge_bar",
    "hookah_bar",
    "beer_garden",
    "brewery",
    "tea_house",
    "cafeteria",
    "catering_service",
    "tea_store",
}
NON_DINING = {
    "hotel",
    "supermarket",
    "gas_station",
    "store",
    "food_store",
    "liquor_store",
    "grocery_store",
    "hypermarket",
    "night_club",
    "spa",
    "book_store",
    "butcher_shop",
    "barber_shop",
    "clothing_store",
    "shopping_mall",
    "florist",
    "parking_garage",
    "art_gallery",
    "swimming_pool",
    "department_store",
    "massage",
    "convenience_store",
    "candy_store",
    "market",
    "corporate_office",
    "wholesaler",
    "service",
    "manufacturer",
    "finance",
    "cultural_center",
    "educational_institution",
    "event_venue",
    "hostel",
    "live_music_venue",
    "sports_complex",
    "sports_club",
    "sports_activity_location",
    "video_arcade",
    "dance_hall",
    "bowling_alley",
    "winery",
    "farm",
    "inn",
    "storage",
    "amusement_center",
    "concert_hall",
    "go_karting_venue",
    "coworking_space",
    "association_or_organization",
    "non_profit_organization",
    "asian_grocery_store",
    "health_food_store",
    "general_store",
    "movie_theater",
    "toy_store",
    "real_estate_agency",
    "jewelry_store",
    "airport",
    "hair_salon",
    "electronics_store",
    "bicycle_store",
    "sporting_goods_store",
    "massage_spa",
    "car_dealer",
    "pet_care",
    "library",
    "cosmetics_store",
    "cell_phone_store",
    "furniture_store",
    "home_improvement_store",
    "gift_shop",
    "travel_agency",
    "convention_center",
    "tennis_court",
    "school",
    "shipping_service",
    "consultant",
    "observation_deck",
    "business_center",
    "performing_arts_theater",
    "car_repair",
    "barbecue_area",
    "gym",
    "fitness_center",
    "lodging",
    "banquet_hall",
    "wedding_venue",
    "karaoke",
    "home_goods_store",
    "rest_stop",
    "car_wash",
    "supplier",
    "pharmacy",
    "drugstore",
    "discount_store",
    "comedy_club",
    "casino",
    "garden",
    "park",
    "bed_and_breakfast",
    "extended_stay_hotel",
    "resort_hotel",
    "farmstay",
    "budget_japanese_inn",
    "transportation_service",
    "courier_service",
    "tourist_attraction",
    "historical_landmark",
    "historical_place",
    "botanical_garden",
    "amusement_park",
    "playground",
    "indoor_playground",
    "ice_skating_rink",
    "race_course",
    "sports_school",
    "sports_coaching",
    "womens_clothing_store",
    "body_art_service",
    "makeup_artist",
    "television_studio",
    "movie_rental",
    "general_contractor",
    "child_care_agency",
    "sauna",
    "public_bath",
    "wellness_center",
    "auditorium",
    "atm",
    "parking",
    "parking_lot",
    "hair_care",
    "health",
}

# City strings that name a place clearly outside the Milan metropolitan area even though
# the seed's coordinates are all inside the Milan bbox — the flat `city` field is
# unreliable (see eda-report.md §3). Flagged for review, not dropped.
OUT_OF_AREA_CITIES = {
    "torino",
    "bergamo",
    "sasso marconi",
    "vairano patenora",
    "martina franca",
    "bazzana superiore",
}

# English -> Italian canonical city aliases. Milan is the only EN/IT twin in the seed.
CITY_ALIASES = {"milan": "Milano"}

_GEOGRAPHIC_NAME_TOKENS = ("metropolitan city",)

# Google amenity/service booleans -> snake_case clean-doc fields.
_AMENITY_FIELDS = {
    "dineIn": "dine_in",
    "takeout": "takeout",
    "delivery": "delivery",
    "reservable": "reservable",
    "curbsidePickup": "curbside_pickup",
    "outdoorSeating": "outdoor_seating",
    "servesVegetarianFood": "serves_vegetarian_food",
    "servesBreakfast": "serves_breakfast",
    "servesLunch": "serves_lunch",
    "servesDinner": "serves_dinner",
    "servesBeer": "serves_beer",
    "servesWine": "serves_wine",
    "servesCocktails": "serves_cocktails",
    "servesCoffee": "serves_coffee",
    "servesDessert": "serves_dessert",
    "liveMusic": "live_music",
    "goodForChildren": "good_for_children",
    "goodForGroups": "good_for_groups",
    "allowsDogs": "allows_dogs",
    "restroom": "restroom",
    "menuForChildren": "menu_for_children",
    "goodForWatchingSports": "good_for_watching_sports",
}


def _clean_optional_text(value: Any) -> str | None:
    """Trim + collapse whitespace; blank/whitespace-only/``None`` -> ``None``.

    Used for optional free-text fields (website, phone) so empty strings do not count
    as "present".
    """
    if value is None:
        return None
    cleaned = _WS_RE.sub(" ", str(value)).strip()
    return cleaned or None


def normalize_name(value: Any) -> str | None:
    """Trim, collapse internal whitespace, and recase ALL-CAPS names to title case.

    Mixed-case names are left as the author wrote them; whitespace-only -> ``None``.
    Title-casing is a **best-effort display heuristic** (``str.title()``) — it can
    mishandle acronyms, brands, and some apostrophes/Italian casing; the unmodified raw
    name remains in ``restaurants_raw_google`` for audit.
    """
    if value is None:
        return None
    cleaned = _WS_RE.sub(" ", str(value)).strip()
    if not cleaned:
        return None
    letters = [c for c in cleaned if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        cleaned = cleaned.title()
    return cleaned


def normalize_address(value: Any) -> str | None:
    """Trim, collapse whitespace, and standardize comma separators."""
    if value is None:
        return None
    cleaned = _WS_RE.sub(" ", str(value)).strip()
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned).strip(" ,")
    return cleaned or None


def canonical_city(value: Any) -> str | None:
    """Canonicalize a city/locality string: trim, recase, EN->IT alias.

    Italian is canonical, so the only EN/IT twin in the seed, ``"Milan"``, becomes
    ``"Milano"``. All-caps / all-lower inputs are title-cased; proper-cased names are
    left untouched. Blank input -> ``None``.
    """
    if value is None:
        return None
    cleaned = _WS_RE.sub(" ", str(value)).strip()
    if not cleaned:
        return None
    alias = CITY_ALIASES.get(cleaned.lower())
    if alias:
        return alias
    letters = [c for c in cleaned if c.isalpha()]
    if letters and (all(c.isupper() for c in letters) or all(c.islower() for c in letters)):
        cleaned = cleaned.title()
    return cleaned


def is_city_out_of_area(city: Any) -> bool:
    """True when the (canonical) city names a place outside the Milan metro."""
    if city is None:
        return False
    return str(city).strip().lower() in OUT_OF_AREA_CITIES


def extract_address_parts(address_components: Any) -> dict[str, str | None]:
    """Lookup structured address parts from Google's ``addressComponents`` list.

    Each component carries a ``types`` list and ``longText``/``shortText``. Returns a
    dict with street / house_number / postal_code / locality / province / country; any
    part not present is ``None``. A reliable lookup (components present ~100%), not a
    free-text parse.
    """
    parts: dict[str, str | None] = {
        "street": None,
        "house_number": None,
        "postal_code": None,
        "locality": None,
        "province": None,
        "country": None,
    }
    if not isinstance(address_components, list):
        return parts
    for comp in address_components:
        if not isinstance(comp, dict):
            continue
        types = comp.get("types") or []
        long_text = comp.get("longText")
        short_text = comp.get("shortText")
        if "street_number" in types:
            parts["house_number"] = long_text
        elif "route" in types:
            parts["street"] = long_text
        elif "postal_code" in types:
            parts["postal_code"] = long_text
        elif "locality" in types:
            parts["locality"] = long_text
        elif "administrative_area_level_2" in types:
            parts["province"] = short_text or long_text  # e.g. "MI"
        elif "country" in types:
            parts["country"] = long_text
    return parts


def classify_tier(primary_type: Any, types: Any = None) -> str:
    """Classify a venue into a dining-relevance tier.

    ``restaurant`` / ``cafe_bar_bakery`` are in scope; ``non_dining`` / ``unknown`` are
    out of scope. Uses ``primary_type`` first, then the ``types`` list as a tiebreaker.
    """
    pt = primary_type if isinstance(primary_type, str) else None
    if pt:
        if pt.endswith("_restaurant") or pt in RESTAURANT_EXTRA:
            return "restaurant"
        if pt in CAFE_BAR_BAKERY:
            return "cafe_bar_bakery"
        if pt in NON_DINING:
            return "non_dining"
    tlist = [t for t in (types or []) if isinstance(t, str)]
    if any(t.endswith("_restaurant") or t in RESTAURANT_EXTRA for t in tlist):
        return "restaurant"
    if any(t in CAFE_BAR_BAKERY for t in tlist):
        return "cafe_bar_bakery"
    if any(t in NON_DINING for t in tlist):
        return "non_dining"
    return "unknown"


def is_dining(category_tier: str) -> bool:
    """In scope when the tier is a restaurant or a cafe/bar/bakery."""
    return category_tier in {"restaurant", "cafe_bar_bakery"}


def is_geographic_name(name: Any, locality: Any = None) -> bool:
    """True when ``name`` is a place string (region / city / CAP) rather than a venue."""
    if name is None:
        return False
    nm = _WS_RE.sub(" ", str(name)).strip().lower()
    if not nm:
        return False
    if any(token in nm for token in _GEOGRAPHIC_NAME_TOKENS):
        return True
    if nm in {"milan", "milano"}:
        return True
    if nm.isdigit() and len(nm) == 5:  # bare Italian CAP
        return True
    if locality and nm == str(locality).strip().lower():
        return True
    return False


def slim_reviews(reviews: Any) -> list[dict[str, Any]]:
    """Project Google reviews to ``{rating, text, language, publish_time, author}``.

    Keeps up to 5 reviews; drops URL / photo / resource-path cruft. The full reviews
    remain in ``restaurants_raw_google`` for the optional LLM text-extraction extension.
    """
    if not isinstance(reviews, list):
        return []
    slimmed: list[dict[str, Any]] = []
    for review in reviews[:5]:
        if not isinstance(review, dict):
            continue
        text_obj = review.get("text") or review.get("originalText") or {}
        if not isinstance(text_obj, dict):
            text_obj = {}
        author = (review.get("authorAttribution") or {}).get("displayName")
        slimmed.append(
            {
                "rating": review.get("rating"),
                "text": text_obj.get("text"),
                "language": text_obj.get("languageCode"),
                "publish_time": review.get("publishTime"),
                "author": author,
            }
        )
    return slimmed


def count_photos(photos: Any) -> int:
    """Number of photo-metadata objects Google returned (a richness/popularity signal)."""
    return len(photos) if isinstance(photos, list) else 0


def parse_price_range(price_range: Any) -> dict[str, Any] | None:
    """Compact Google's ``priceRange`` into ``{start, end, currency}`` (ints/EUR)."""
    if not isinstance(price_range, dict):
        return None
    start = price_range.get("startPrice") or {}
    end = price_range.get("endPrice") or {}

    def _units(price: Any) -> int | None:
        if not isinstance(price, dict):
            return None
        units = price.get("units")
        try:
            return int(units) if units is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "start": _units(start),
        "end": _units(end),
        "currency": start.get("currencyCode") or end.get("currencyCode"),
    }


def amenity_flags(details: dict[str, Any]) -> dict[str, bool]:
    """Snake-case the Google service/amenity booleans present in ``details``.

    Only real booleans are kept, so an unexpected non-bool value (``None``, a string, a
    future shape change) never leaks a non-boolean into the clean schema.
    """
    return {
        snake: value
        for google, snake in _AMENITY_FIELDS.items()
        if isinstance((value := details.get(google)), bool)
    }


def _coerce_rating(value: Any) -> float | None:
    """Pass through a numeric rating in ``[1.0, 5.0]``; anything else -> ``None``.

    Google data is already typed/valid (EDA), so this is a defensive guard, not a parser.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    rating = float(value)
    return rating if 1.0 <= rating <= 5.0 else None


def _coerce_count(value: Any) -> int | None:
    """Pass through a non-negative integer review count; anything else -> ``None``.

    Accepts whole-valued floats (e.g. ``200.0``) so a value that round-tripped through
    JSON/float is not silently dropped; non-integer floats and other types -> ``None``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    count = int(value)
    return count if count >= 0 else None


def clean_record(raw: dict[str, Any], *, low_review_threshold: int = 10) -> dict[str, Any]:
    """Clean one raw Google record into a lean clean document (pure).

    Projects the relevant fields out of the heavy ``details`` blob, normalizes the
    name/city, lifts structured address parts, classifies dining relevance, derives
    quality flags + feature fields, and slims reviews. Coordinates are copied verbatim
    (authoritative — never recomputed). ``rating`` / ``review_count`` prefer
    ``details.*`` (fetched after the seed capture -> fresher), but **coalesce** to the
    top-level value when the detail field is missing, so a record where details lacks a
    rating but the top-level has one is not discarded. Does not set ``_id`` or apply drop
    rules — that is the transform layer's job.
    """
    details = raw.get("details")
    if not isinstance(details, dict):
        details = {}

    parts = extract_address_parts(details.get("addressComponents"))
    locality = parts["locality"]
    city = canonical_city(locality or raw.get("city"))
    category_tier = classify_tier(raw.get("primary_type"), raw.get("types"))
    # Prefer the fresher details.* value, fall back to the top-level seed field.
    rating = _coerce_rating(details.get("rating"))
    if rating is None:
        rating = _coerce_rating(raw.get("rating"))
    review_count = _coerce_count(details.get("userRatingCount"))
    if review_count is None:
        review_count = _coerce_count(raw.get("user_rating_count"))
    business_status = details.get("businessStatus")

    is_operational = business_status == "OPERATIONAL"
    has_rating = rating is not None
    # Low-review is a count concept, independent of whether a rating is present.
    low_review = review_count is not None and review_count < low_review_threshold
    name_is_geo = is_geographic_name(raw.get("name"), locality)
    city_out = is_city_out_of_area(city)
    website = _clean_optional_text(details.get("websiteUri"))
    phone = _clean_optional_text(
        details.get("internationalPhoneNumber") or details.get("nationalPhoneNumber")
    )
    website = normalize_website(website)
    phone = normalize_phone(phone)

    flags: list[str] = []
    if category_tier == "non_dining":
        flags.append("non_dining")
    if name_is_geo:
        flags.append("name_is_geographic")
    if business_status is not None and not is_operational:
        flags.append("not_operational")
    if low_review:
        flags.append("low_review")
    if city_out:
        flags.append("city_out_of_area")

    doc: dict[str, Any] = {
        "place_id": raw.get("place_id"),
        "name": normalize_name(raw.get("name")),
        "latitude": raw.get("latitude"),
        "longitude": raw.get("longitude"),
        "address": normalize_address(raw.get("formatted_address")),
        "street": parts["street"],
        "house_number": parts["house_number"],
        "postal_code": parts["postal_code"],
        "locality": locality,
        "province": parts["province"],
        "country": parts["country"],
        "city": city,
        "city_out_of_area": city_out,
        "rating": rating,
        "review_count": review_count,
        "has_rating": has_rating,
        "low_review": low_review,
        "primary_type": raw.get("primary_type"),
        "types": raw.get("types") or [],
        "category_tier": category_tier,
        "is_dining": is_dining(category_tier),
        "business_status": business_status,
        "is_operational": is_operational,
        "name_is_geographic": name_is_geo,
        "flags": flags,
        "photo_count": count_photos(details.get("photos")),
        "price_level": details.get("priceLevel"),
        "price_range": parse_price_range(details.get("priceRange")),
        "has_website": website is not None,
        "has_phone": phone is not None,
        "website": website,
        "phone": phone,
        "reviews": slim_reviews(details.get("reviews")),
    }
    doc.update(amenity_flags(details))
    return doc
