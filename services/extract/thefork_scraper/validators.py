from __future__ import annotations

from typing import Any

from .models import RestaurantRecord

DETAIL_FIELDS = [
    "restaurant_name",
    "address",
    "latitude",
    "longitude",
    "rating",
    "review_count",
    "cuisine_type",
    "price_range",
    "discount",
    "photo_count",
    "website",
    "social_links",
    "phone_number",
    "email",
    "working_days_hours",
    "working_hours_structured",
    "restaurant_url",
    "review_snippets",
    "reviews",
    "detail_scraped",
]


def build_validation_report(
    records: list[RestaurantRecord],
    fields_removed: list[str] | None = None,
    debug_notes: list[str] | None = None,
) -> dict[str, Any]:
    payload = [record.to_dict() for record in records]
    total_records = len(payload)
    coverage: dict[str, dict[str, float | int]] = {}
    always_empty_fields: list[str] = []

    for field_name in DETAIL_FIELDS:
        non_null = sum(1 for item in payload if has_value(item.get(field_name)))
        null_count = total_records - non_null
        coverage_pct = round((non_null / total_records) * 100, 2) if total_records else 0.0
        coverage[field_name] = {
            "non_null": non_null,
            "null": null_count,
            "coverage_pct": coverage_pct,
        }
        if total_records and non_null == 0:
            always_empty_fields.append(field_name)

    notes = list(debug_notes or [])
    if always_empty_fields:
        notes.append(
            "Always-empty fields were checked through JSON-LD, embedded JSON, "
            "visible text, links, and attributes. "
            "They are reported for manual review before any schema pruning."
        )

    return {
        "total_records": total_records,
        "field_coverage": coverage,
        "fields_removed": fields_removed or [],
        "always_empty_fields": always_empty_fields,
        "debug_notes": notes,
    }


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if value == "":
        return False
    if isinstance(value, list) and not value:
        return False
    if isinstance(value, dict) and not value:
        return False
    return True
