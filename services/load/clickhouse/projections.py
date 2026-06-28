"""Pure projection functions: MongoDB document → flat ClickHouse row dict.

Each ``project_<name>`` function takes one raw MongoDB document and returns a
``dict`` whose keys match the ClickHouse column names for that table, or ``None``
when the natural key is missing (the caller skips and counts such records).

Design notes
------------
- **No I/O** — pure, deterministic, fast to test.
- Booleans from MongoDB → ``UInt8`` (0 / 1).
- ``None`` scalars → ``Nullable`` columns (pass ``None`` through; ClickHouse
  accepts Python ``None`` for Nullable columns via clickhouse-connect).
- Missing arrays → empty list ``[]``.
- ``price_level`` can be a ``str`` *or* a ``list[str]`` in the integrated
  collection (tie case). It is coerced to a single ``String``: when it is a
  list, the values are joined with ``" / "``; when it is a str, it is kept as-is.
- The integrated row includes **source join-key columns** extracted from the
  nested ``sources.*.ids`` sub-documents so the three cleaned tables remain
  joinable without loading the full nested evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bool_to_u8(val: Any) -> int:
    """Coerce a MongoDB boolean (or truthy) value to 0 / 1."""
    return 1 if val else 0


def _str(val: Any) -> str:
    """Coerce to str; map None/missing to empty string."""
    if val is None:
        return ""
    return str(val)


def _array_of_str(val: Any) -> list[str]:
    """Ensure a list-of-strings; map None/missing to []."""
    if not val:
        return []
    return [str(v) for v in val]


def _price_level_str(val: Any) -> str:
    """Flatten price_level: str → str, list → joined string."""
    if val is None:
        return ""
    if isinstance(val, list):
        return " / ".join(str(v) for v in val)
    return str(val)


def _nested(doc: dict[str, Any], *keys: str) -> Any:
    """Safely traverse nested dicts; return None when any key is absent."""
    cur: Any = doc
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _int_or_none(val: Any) -> int | None:
    """Coerce to int; map None/non-numeric to None."""
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _present(doc: dict[str, Any], *keys: str) -> int:
    """1 when the nested value is a non-empty string, else 0 (contact presence)."""
    return 1 if _str(_nested(doc, *keys)).strip() else 0


# Google's categorical price level → normalized 1..4 tier.
_GOOGLE_PRICE_TIER = {
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}


def _thefork_price_tier(avg_price_eur: Any) -> int | None:
    """Bin TheFork's average price (EUR) into a 1..4 tier."""
    eur = _int_or_none(avg_price_eur)
    if eur is None:
        return None
    if eur <= 15:
        return 1
    if eur <= 30:
        return 2
    if eur <= 50:
        return 3
    return 4


def _price_tier(doc: dict[str, Any]) -> int | None:
    """Normalized cross-platform price tier (1=cheapest..4).

    Prefers Tripadvisor's 1..4 band (most directly comparable), then Google's
    categorical level, then a binning of TheFork's average EUR price.
    """
    ta = _int_or_none(_nested(doc, "sources", "tripadvisor", "price", "price_tier_level"))
    if ta:
        return ta
    google_level = _str(_nested(doc, "sources", "google", "price", "price_level"))
    if google_level in _GOOGLE_PRICE_TIER:
        return _GOOGLE_PRICE_TIER[google_level]
    return _thefork_price_tier(_nested(doc, "sources", "thefork", "price", "avg_price_eur"))


def _primary_cuisine(doc: dict[str, Any]) -> str:
    """First cuisine label, preferring Tripadvisor (broadest vocabulary)."""
    for platform in ("tripadvisor", "thefork"):
        cuisines = _array_of_str(_nested(doc, "sources", platform, "cuisines"))
        if cuisines:
            return cuisines[0]
    return ""


# ---------------------------------------------------------------------------
# Integrated
# ---------------------------------------------------------------------------

INTEGRATED_COLUMNS: list[str] = [
    "integrated_restaurant_id",
    "google_place_id",
    "tripadvisor_source_url",
    "thefork_source_id",
    "canonical_name",
    "canonical_address",
    "canonical_street",
    "canonical_house_number",
    "canonical_postal_code",
    "canonical_city",
    "latitude",
    "longitude",
    "coordinate_source",
    "has_google",
    "has_tripadvisor",
    "has_thefork",
    "has_all_three_platforms",
    "platform_count",
    "google_rating_5",
    "tripadvisor_rating_5",
    "thefork_rating_raw_10",
    "thefork_rating_5",
    "rating_platform_count",
    "rating_avg_5",
    "rating_range_5",
    "google_review_count",
    "tripadvisor_review_count",
    "thefork_review_count",
    "google_photo_count",
    "tripadvisor_photo_count",
    "thefork_photo_count",
    "google_has_website",
    "google_has_phone",
    "tripadvisor_has_website",
    "tripadvisor_has_phone",
    "tripadvisor_has_email",
    "tripadvisor_cuisines",
    "thefork_cuisines",
    "primary_cuisine",
    "cuisine_tags",
    "cuisine_primary",
    "cuisine_primary_source",
    "cuisine_n_sources",
    "cuisine_agreement",
    "google_price_level",
    "tripadvisor_price_band",
    "tripadvisor_price_tier_level",
    "thefork_avg_price_eur",
    "price_tier",
    "google_category_tier",
    "google_is_dining",
    "website",
    "website_source",
    "website_match_status",
    "phone_match_status",
    "price_level",
    "price_level_source",
    "integration_flags",
    "updated_at",
]


def project_integrated(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Project a ``restaurants_integrated`` MongoDB doc to a flat ClickHouse row."""
    key = doc.get("integrated_restaurant_id")
    if not key or (isinstance(key, str) and not key.strip()):
        return None

    # Lift source join keys from nested sources.*.ids
    google_place_id = _str(_nested(doc, "sources", "google", "ids", "place_id"))
    tripadvisor_source_url = _str(_nested(doc, "sources", "tripadvisor", "ids", "source_url"))
    thefork_source_id = _str(_nested(doc, "sources", "thefork", "ids", "source_id"))

    updated_at = doc.get("_updated_at")
    if not isinstance(updated_at, datetime):
        updated_at = datetime.now(timezone.utc)

    return {
        "integrated_restaurant_id": key,
        "google_place_id": google_place_id,
        "tripadvisor_source_url": tripadvisor_source_url,
        "thefork_source_id": thefork_source_id,
        "canonical_name": _str(doc.get("canonical_name")),
        "canonical_address": _str(doc.get("canonical_address")),
        "canonical_street": _str(doc.get("canonical_street")),
        "canonical_house_number": _str(doc.get("canonical_house_number")),
        "canonical_postal_code": _str(doc.get("canonical_postal_code")),
        "canonical_city": _str(doc.get("canonical_city")),
        "latitude": doc.get("latitude"),
        "longitude": doc.get("longitude"),
        "coordinate_source": _str(doc.get("coordinate_source")),
        "has_google": _bool_to_u8(doc.get("has_google")),
        "has_tripadvisor": _bool_to_u8(doc.get("has_tripadvisor")),
        "has_thefork": _bool_to_u8(doc.get("has_thefork")),
        "has_all_three_platforms": _bool_to_u8(doc.get("has_all_three_platforms")),
        "platform_count": doc.get("platform_count") or 0,
        "google_rating_5": doc.get("google_rating_5"),
        "tripadvisor_rating_5": doc.get("tripadvisor_rating_5"),
        "thefork_rating_raw_10": doc.get("thefork_rating_raw_10"),
        "thefork_rating_5": doc.get("thefork_rating_5"),
        "rating_platform_count": doc.get("rating_platform_count") or 0,
        "rating_avg_5": doc.get("rating_avg_5"),
        "rating_range_5": doc.get("rating_range_5"),
        "google_review_count": doc.get("google_review_count"),
        "tripadvisor_review_count": doc.get("tripadvisor_review_count"),
        "thefork_review_count": doc.get("thefork_review_count"),
        # Per-platform photo counts (lifted from nested sources.*)
        "google_photo_count": _int_or_none(_nested(doc, "sources", "google", "photo_count")),
        "tripadvisor_photo_count": _int_or_none(
            _nested(doc, "sources", "tripadvisor", "photo_count")
        ),
        "thefork_photo_count": _int_or_none(_nested(doc, "sources", "thefork", "photo_count")),
        # Per-platform contact completeness
        "google_has_website": _present(doc, "sources", "google", "contacts", "website"),
        "google_has_phone": _present(doc, "sources", "google", "contacts", "phone"),
        "tripadvisor_has_website": _present(doc, "sources", "tripadvisor", "contacts", "website"),
        "tripadvisor_has_phone": _present(doc, "sources", "tripadvisor", "contacts", "phone"),
        "tripadvisor_has_email": _present(doc, "sources", "tripadvisor", "contacts", "email"),
        # Cuisine labels
        "tripadvisor_cuisines": _array_of_str(_nested(doc, "sources", "tripadvisor", "cuisines")),
        "thefork_cuisines": _array_of_str(_nested(doc, "sources", "thefork", "cuisines")),
        "primary_cuisine": _primary_cuisine(doc),
        # Canonical cuisine reconciled across all three platforms (computed in the integration step)
        "cuisine_tags": _array_of_str(doc.get("cuisine_tags")),
        "cuisine_primary": _str(doc.get("cuisine_primary")),
        "cuisine_primary_source": _str(doc.get("cuisine_primary_source")),
        "cuisine_n_sources": doc.get("cuisine_n_sources") or 0,
        "cuisine_agreement": _str(doc.get("cuisine_agreement")),
        # Per-platform price + normalized tier
        "google_price_level": _str(_nested(doc, "sources", "google", "price", "price_level")),
        "tripadvisor_price_band": _str(
            _nested(doc, "sources", "tripadvisor", "price", "price_band")
        ),
        "tripadvisor_price_tier_level": _int_or_none(
            _nested(doc, "sources", "tripadvisor", "price", "price_tier_level")
        ),
        "thefork_avg_price_eur": _int_or_none(
            _nested(doc, "sources", "thefork", "price", "avg_price_eur")
        ),
        "price_tier": _price_tier(doc),
        # Google classification
        "google_category_tier": _str(
            _nested(doc, "sources", "google", "classification", "category_tier")
        ),
        "google_is_dining": _bool_to_u8(
            _nested(doc, "sources", "google", "classification", "is_dining")
        ),
        "website": _str(doc.get("website")),
        "website_source": _str(doc.get("website_source")),
        "website_match_status": _str(doc.get("website_match_status")),
        "phone_match_status": _str(doc.get("phone_match_status")),
        "price_level": _price_level_str(doc.get("price_level")),
        "price_level_source": _str(doc.get("price_level_source")),
        "integration_flags": _array_of_str(doc.get("integration_flags")),
        "updated_at": updated_at,
    }


# ---------------------------------------------------------------------------
# Clean Google
# ---------------------------------------------------------------------------

CLEAN_GOOGLE_COLUMNS: list[str] = [
    "place_id",
    "name",
    "latitude",
    "longitude",
    "address",
    "street",
    "house_number",
    "postal_code",
    "locality",
    "province",
    "country",
    "city",
    "city_out_of_area",
    "rating",
    "review_count",
    "has_rating",
    "low_review",
    "primary_type",
    "types",
    "category_tier",
    "is_dining",
    "is_operational",
    "business_status",
    "photo_count",
    "price_level",
    "has_website",
    "has_phone",
    "website",
    "phone",
    "flags",
]


def project_clean_google(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Project a ``restaurants_clean_google`` MongoDB doc to a flat ClickHouse row."""
    key = doc.get("place_id")
    if not key or (isinstance(key, str) and not key.strip()):
        return None

    # price_level in clean_google is a plain string; coerce defensively
    price = doc.get("price_level")
    price_str = _price_level_str(price) if price is not None else ""

    return {
        "place_id": key,
        "name": _str(doc.get("name")),
        "latitude": doc.get("latitude"),
        "longitude": doc.get("longitude"),
        "address": _str(doc.get("address")),
        "street": _str(doc.get("street")),
        "house_number": _str(doc.get("house_number")),
        "postal_code": _str(doc.get("postal_code")),
        "locality": _str(doc.get("locality")),
        "province": _str(doc.get("province")),
        "country": _str(doc.get("country")),
        "city": _str(doc.get("city")),
        "city_out_of_area": _bool_to_u8(doc.get("city_out_of_area")),
        "rating": doc.get("rating"),
        "review_count": doc.get("review_count"),
        "has_rating": _bool_to_u8(doc.get("has_rating")),
        "low_review": _bool_to_u8(doc.get("low_review")),
        "primary_type": _str(doc.get("primary_type")),
        "types": _array_of_str(doc.get("types")),
        "category_tier": _str(doc.get("category_tier")),
        "is_dining": _bool_to_u8(doc.get("is_dining")),
        "is_operational": _bool_to_u8(doc.get("is_operational")),
        "business_status": _str(doc.get("business_status")),
        "photo_count": doc.get("photo_count") or 0,
        "price_level": price_str,
        "has_website": _bool_to_u8(doc.get("has_website")),
        "has_phone": _bool_to_u8(doc.get("has_phone")),
        "website": _str(doc.get("website")),
        "phone": _str(doc.get("phone")),
        "flags": _array_of_str(doc.get("flags")),
    }


# ---------------------------------------------------------------------------
# Clean Tripadvisor
# ---------------------------------------------------------------------------

CLEAN_TRIPADVISOR_COLUMNS: list[str] = [
    "source_url",
    "ta_location_id",
    "restaurant_name",
    "rating",
    "total_review",
    "address",
    "street",
    "house_number",
    "postal_code",
    "city",
    "latitude",
    "longitude",
    "has_coordinates",
    "photo_count",
    "price_band",
    "price_tier_level",
    "cuisines",
    "has_rating",
    "has_review_count",
    "low_review",
    "has_address",
    "has_reviews",
    "has_hours",
    "has_phone",
    "has_website",
    "has_email",
    "website",
    "phone",
    "email",
    "flags",
]


def project_clean_tripadvisor(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Project a ``restaurants_clean_tripadvisor`` MongoDB doc to a flat ClickHouse row."""
    key = doc.get("source_url")
    if not key or (isinstance(key, str) and not key.strip()):
        return None

    return {
        "source_url": key,
        "ta_location_id": _str(doc.get("ta_location_id")),
        "restaurant_name": _str(doc.get("restaurant_name")),
        "rating": doc.get("rating"),
        "total_review": doc.get("total_review"),
        "address": _str(doc.get("address")),
        "street": _str(doc.get("street")),
        "house_number": _str(doc.get("house_number")),
        "postal_code": _str(doc.get("postal_code")),
        "city": _str(doc.get("city")),
        "latitude": doc.get("latitude"),
        "longitude": doc.get("longitude"),
        "has_coordinates": _bool_to_u8(doc.get("has_coordinates")),
        "photo_count": doc.get("photo_count"),
        "price_band": _str(doc.get("price_band")),
        "price_tier_level": doc.get("price_tier_level"),
        "cuisines": _array_of_str(doc.get("cuisines")),
        "has_rating": _bool_to_u8(doc.get("has_rating")),
        "has_review_count": _bool_to_u8(doc.get("has_review_count")),
        "low_review": _bool_to_u8(doc.get("low_review")),
        "has_address": _bool_to_u8(doc.get("has_address")),
        "has_reviews": _bool_to_u8(doc.get("has_reviews")),
        "has_hours": _bool_to_u8(doc.get("has_hours")),
        "has_phone": _bool_to_u8(doc.get("has_phone")),
        "has_website": _bool_to_u8(doc.get("has_website")),
        "has_email": _bool_to_u8(doc.get("has_email")),
        "website": _str(doc.get("website")),
        "phone": _str(doc.get("phone")),
        "email": _str(doc.get("email")),
        "flags": _array_of_str(doc.get("flags")),
    }


# ---------------------------------------------------------------------------
# Clean TheFork
# ---------------------------------------------------------------------------

CLEAN_THEFORK_COLUMNS: list[str] = [
    "source_id",
    "source",
    "tf_id",
    "restaurant_url",
    "restaurant_name",
    "latitude",
    "longitude",
    "address",
    "street",
    "house_number",
    "postal_code",
    "city",
    "rating",
    "review_count",
    "has_rating",
    "has_review_count",
    "low_review",
    "avg_price_eur",
    "discount_pct",
    "has_discount",
    "cuisines",
    "dietary_options",
    "has_hours",
    "photo_count",
    "has_reviews",
    "sample_size",
    "sample_avg_rating",
    "rating_sample_divergent",
    "flags",
]


def project_clean_thefork(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Project a ``restaurants_clean_thefork`` MongoDB doc to a flat ClickHouse row."""
    key = doc.get("source_id")
    if not key or (isinstance(key, str) and not key.strip()):
        return None

    return {
        "source_id": key,
        "source": _str(doc.get("source")),
        "tf_id": _str(doc.get("tf_id")),
        "restaurant_url": _str(doc.get("restaurant_url")),
        "restaurant_name": _str(doc.get("restaurant_name")),
        "latitude": doc.get("latitude"),
        "longitude": doc.get("longitude"),
        "address": _str(doc.get("address")),
        "street": _str(doc.get("street")),
        "house_number": _str(doc.get("house_number")),
        "postal_code": _str(doc.get("postal_code")),
        "city": _str(doc.get("city")),
        "rating": doc.get("rating"),
        "review_count": doc.get("review_count"),
        "has_rating": _bool_to_u8(doc.get("has_rating")),
        "has_review_count": _bool_to_u8(doc.get("has_review_count")),
        "low_review": _bool_to_u8(doc.get("low_review")),
        "avg_price_eur": doc.get("avg_price_eur"),
        "discount_pct": doc.get("discount_pct"),
        "has_discount": _bool_to_u8(doc.get("has_discount")),
        "cuisines": _array_of_str(doc.get("cuisines")),
        "dietary_options": _array_of_str(doc.get("dietary_options")),
        "has_hours": _bool_to_u8(doc.get("has_hours")),
        "photo_count": doc.get("photo_count"),
        "has_reviews": _bool_to_u8(doc.get("has_reviews")),
        "sample_size": doc.get("sample_size") or 0,
        "sample_avg_rating": doc.get("sample_avg_rating"),
        "rating_sample_divergent": _bool_to_u8(doc.get("rating_sample_divergent")),
        "flags": _array_of_str(doc.get("flags")),
    }
