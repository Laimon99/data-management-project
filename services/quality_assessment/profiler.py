from __future__ import annotations

import csv
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .normalization import (
    first_present,
    in_milan_area,
    is_missing,
    normalize_text,
    parse_float,
    parse_int,
)

Accessor = Callable[[dict[str, Any]], Any]
Validator = Callable[[Any], bool]
DEFAULT_REFRESH_TARGET_HOURS = 48.0
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
ANOMALY_FIELDNAMES = ["source", "record_id", "issue_type", "field", "value", "detail"]
COVERAGE_FIELDNAMES = ["source", "field", "present", "missing", "coverage_pct"]
SCORE_FIELDNAMES = [
    "source",
    "overall_quality_score_pct",
    "completeness_score_pct",
    "critical_completeness_score_pct",
    "validity_score_pct",
    "spatial_readiness_score_pct",
    "uniqueness_score_pct",
    "timeliness_score_pct",
    "timestamp_coverage_pct",
    "collection_duration_hours",
    "refresh_target_hours",
    "reliability_score_pct",
    "anomaly_count",
    "record_count",
]


@dataclass(frozen=True)
class SourceConfig:
    name: str
    path: Path
    file_format: str
    id_field: str
    rating_scale: float
    fields: dict[str, Accessor]
    critical_fields: tuple[str, ...]
    rating_field: str = "rating"
    review_count_field: str = "review_count"
    latitude_field: str = "latitude"
    longitude_field: str = "longitude"
    timestamp_fields: tuple[str, ...] = ()
    format_validators: dict[str, Validator] = dataclass_field(default_factory=dict)
    collection_duration_hours: float | None = None
    collection_duration_source: str = "observed timestamp window"
    refresh_target_hours: float = DEFAULT_REFRESH_TARGET_HOURS


def get_path(record: dict[str, Any], path: str) -> Any:
    current: Any = record
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def make_accessor(path: str) -> Accessor:
    return lambda record: get_path(record, path)


def valid_present_value(value: Any) -> bool:
    return not is_missing(value)


def valid_non_empty_text(value: Any) -> bool:
    return not is_missing(value) and bool(str(value).strip())


def valid_collection_or_text(value: Any) -> bool:
    if is_missing(value):
        return False
    if isinstance(value, (list, dict)):
        return bool(value)
    return bool(str(value).strip())


def valid_url(value: Any) -> bool:
    if is_missing(value):
        return False
    return bool(URL_RE.match(str(value).strip()))


def valid_email(value: Any) -> bool:
    if is_missing(value):
        return False
    return bool(EMAIL_RE.match(str(value).strip()))


def valid_phone(value: Any) -> bool:
    if is_missing(value):
        return False
    digits = re.sub(r"\D", "", str(value))
    return len(digits) >= 6


def rating_validator(max_score: float) -> Validator:
    def validate(value: Any) -> bool:
        parsed = parse_float(value)
        return parsed is not None and 0 <= parsed <= max_score

    return validate


def valid_non_negative_int(value: Any) -> bool:
    parsed = parse_int(value)
    return parsed is not None and parsed >= 0


def valid_latitude(value: Any) -> bool:
    parsed = parse_float(value)
    return parsed is not None and -90 <= parsed <= 90


def valid_longitude(value: Any) -> bool:
    parsed = parse_float(value)
    return parsed is not None and -180 <= parsed <= 180


def valid_timestamp(value: Any) -> bool:
    return parse_datetime(value) is not None


def valid_google_price(value: Any) -> bool:
    if is_missing(value):
        return False
    if isinstance(value, dict):
        return any(not is_missing(item) for item in value.values())
    text = str(value).strip()
    return text.startswith("PRICE_LEVEL_") or parse_float(text) is not None


def valid_tripadvisor_price_range(value: Any) -> bool:
    if is_missing(value):
        return False
    text = str(value).strip()
    allowed = set("$\u20ac£- ")
    return any(symbol in text for symbol in "$\u20ac£") and all(char in allowed for char in text)


def valid_euro_price_amount(value: Any) -> bool:
    if is_missing(value):
        return False
    text = str(value).strip().lower()
    return parse_float(text) is not None and ("\u20ac" in text or "eur" in text)


def valid_discount(value: Any) -> bool:
    if is_missing(value):
        return False
    text = str(value).strip()
    return "%" in text and parse_float(text) is not None


def valid_business_status(value: Any) -> bool:
    if is_missing(value):
        return False
    return str(value).strip().upper() in {
        "OPERATIONAL",
        "CLOSED_TEMPORARILY",
        "CLOSED_PERMANENTLY",
    }


def valid_bool(value: Any) -> bool:
    return isinstance(value, bool)


def google_config(path: Path) -> SourceConfig:
    fields: dict[str, Accessor] = {
        "place_id": make_accessor("place_id"),
        "name": make_accessor("name"),
        "address": make_accessor("formatted_address"),
        "city": make_accessor("city"),
        "latitude": make_accessor("latitude"),
        "longitude": make_accessor("longitude"),
        "rating": make_accessor("rating"),
        "review_count": make_accessor("user_rating_count"),
        "types": make_accessor("types"),
        "primary_type": make_accessor("primary_type"),
        "details": make_accessor("details"),
        "phone_number": lambda r: first_present(
            get_path(r, "details.internationalPhoneNumber"),
            get_path(r, "details.nationalPhoneNumber"),
        ),
        "website": make_accessor("details.websiteUri"),
        "opening_hours": lambda r: first_present(
            get_path(r, "details.regularOpeningHours"),
            get_path(r, "details.currentOpeningHours"),
        ),
        "reviews": make_accessor("details.reviews"),
        "price": lambda r: first_present(
            get_path(r, "details.priceLevel"),
            get_path(r, "details.priceRange"),
        ),
        "business_status": make_accessor("details.businessStatus"),
        "details_fetched_at": make_accessor("details_fetched_at"),
        "seed_collected_at": make_accessor("seed_collected_at"),
    }
    return SourceConfig(
        name="Google Places",
        path=path,
        file_format="jsonl",
        id_field="place_id",
        rating_scale=5.0,
        fields=fields,
        critical_fields=(
            "place_id",
            "name",
            "address",
            "latitude",
            "longitude",
            "rating",
            "review_count",
        ),
        timestamp_fields=("details_fetched_at", "seed_collected_at"),
        format_validators={
            "place_id": valid_non_empty_text,
            "name": valid_non_empty_text,
            "address": valid_non_empty_text,
            "city": valid_non_empty_text,
            "latitude": valid_latitude,
            "longitude": valid_longitude,
            "rating": rating_validator(5.0),
            "review_count": valid_non_negative_int,
            "types": valid_collection_or_text,
            "primary_type": valid_non_empty_text,
            "details": valid_collection_or_text,
            "phone_number": valid_phone,
            "website": valid_url,
            "opening_hours": valid_collection_or_text,
            "reviews": valid_collection_or_text,
            "price": valid_google_price,
            "business_status": valid_business_status,
            "details_fetched_at": valid_timestamp,
            "seed_collected_at": valid_timestamp,
        },
    )


def tripadvisor_config(path: Path) -> SourceConfig:
    fields: dict[str, Accessor] = {
        "source_url": make_accessor("source_url"),
        "restaurant_name": make_accessor("restaurant_name"),
        "address": make_accessor("address"),
        "rating": make_accessor("rating"),
        "review_count": make_accessor("total_review"),
        "cuisine_type": make_accessor("cuisine_type"),
        "price_range": make_accessor("price_range"),
        "photo_count": make_accessor("number_photo_uploaded"),
        "website": make_accessor("website"),
        "phone_number": make_accessor("phone_number"),
        "email": make_accessor("email"),
        "opening_hours": make_accessor("working_days_hours"),
        "reviews": make_accessor("review"),
    }
    return SourceConfig(
        name="Tripadvisor",
        path=path,
        file_format="json",
        id_field="source_url",
        rating_scale=5.0,
        fields=fields,
        critical_fields=("source_url", "restaurant_name", "address", "rating", "review_count"),
        format_validators={
            "source_url": valid_url,
            "restaurant_name": valid_non_empty_text,
            "address": valid_non_empty_text,
            "rating": rating_validator(5.0),
            "review_count": valid_non_negative_int,
            "cuisine_type": valid_collection_or_text,
            "price_range": valid_tripadvisor_price_range,
            "photo_count": valid_non_negative_int,
            "website": valid_url,
            "phone_number": valid_phone,
            "email": valid_email,
            "opening_hours": valid_collection_or_text,
            "reviews": valid_collection_or_text,
        },
        collection_duration_hours=27.0,
        collection_duration_source="configured scraper runtime estimate",
    )


def thefork_config(path: Path) -> SourceConfig:
    fields: dict[str, Accessor] = {
        "source_id": make_accessor("source_id"),
        "restaurant_url": make_accessor("restaurant_url"),
        "restaurant_name": make_accessor("restaurant_name"),
        "address": make_accessor("address"),
        "city": make_accessor("city"),
        "latitude": make_accessor("latitude"),
        "longitude": make_accessor("longitude"),
        "rating": make_accessor("rating"),
        "review_count": make_accessor("review_count"),
        "cuisine_type": make_accessor("cuisine_type"),
        "price_range": make_accessor("price_range"),
        "discount": make_accessor("discount"),
        "photo_count": make_accessor("photo_count"),
        "website": make_accessor("website"),
        "phone_number": make_accessor("phone_number"),
        "email": make_accessor("email"),
        "opening_hours": make_accessor("working_days_hours"),
        "reviews": make_accessor("reviews"),
        "detail_scraped": make_accessor("detail_scraped"),
        "scraped_at": make_accessor("scraped_at"),
    }
    return SourceConfig(
        name="TheFork",
        path=path,
        file_format="json",
        id_field="source_id",
        rating_scale=10.0,
        fields=fields,
        critical_fields=(
            "source_id",
            "restaurant_name",
            "address",
            "latitude",
            "longitude",
            "rating",
            "review_count",
        ),
        timestamp_fields=("scraped_at",),
        format_validators={
            "source_id": valid_present_value,
            "restaurant_url": valid_url,
            "restaurant_name": valid_non_empty_text,
            "address": valid_non_empty_text,
            "city": valid_non_empty_text,
            "latitude": valid_latitude,
            "longitude": valid_longitude,
            "rating": rating_validator(10.0),
            "review_count": valid_non_negative_int,
            "cuisine_type": valid_collection_or_text,
            "price_range": valid_euro_price_amount,
            "discount": valid_discount,
            "photo_count": valid_non_negative_int,
            "website": valid_url,
            "phone_number": valid_phone,
            "email": valid_email,
            "opening_hours": valid_collection_or_text,
            "reviews": valid_collection_or_text,
            "detail_scraped": valid_bool,
            "scraped_at": valid_timestamp,
        },
        collection_duration_hours=2.0,
        collection_duration_source="configured scraper runtime estimate",
    )


def iter_records(config: SourceConfig) -> Iterable[dict[str, Any]]:
    if not config.path.exists():
        raise FileNotFoundError(f"Missing input dataset for {config.name}: {config.path}")
    if config.file_format == "jsonl":
        with config.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if line.strip():
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError as exc:
                        yield {"__invalid_json__": str(exc), "__line_number__": line_number}
    elif config.file_format == "json":
        data = json.loads(config.path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"{config.path} must contain a JSON array")
        yield from data
    else:
        raise ValueError(f"Unsupported file format: {config.file_format}")


def analyze_source(config: SourceConfig, low_review_threshold: int = 20) -> dict[str, Any]:
    generated_at = datetime.now(UTC)
    record_count = 0
    present_counts = Counter[str]()
    ids = Counter[str]()
    name_address_keys = Counter[str]()
    record_summaries: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    rating_values: list[float] = []
    review_values: list[int] = []
    timestamp_values: list[datetime] = []
    timestamp_present_counts = Counter[str]()
    timestamp_parseable_counts = Counter[str]()
    records_with_timestamp = 0
    valid_coordinates = 0
    coordinates_present = 0
    coordinates_in_area = 0
    format_checked_values = 0
    format_valid_values = 0
    format_invalid_fields = Counter[str]()
    invalid_json_lines = 0

    for index, record in enumerate(iter_records(config), 1):
        if "__invalid_json__" in record:
            invalid_json_lines += 1
            anomalies.append(
                anomaly(
                    config.name,
                    str(index),
                    "invalid_json",
                    "record",
                    "",
                    record["__invalid_json__"],
                )
            )
            continue

        record_count += 1
        values = {field: accessor(record) for field, accessor in config.fields.items()}
        source_id = values.get(config.id_field)
        source_id_text = str(source_id) if not is_missing(source_id) else f"row:{index}"
        for field, value in values.items():
            if not is_missing(value):
                present_counts[field] += 1

        fields_with_specific_flags = {
            config.rating_field,
            config.review_count_field,
            *config.timestamp_fields,
        }
        for field, validator in config.format_validators.items():
            value = values.get(field)
            if is_missing(value):
                continue
            format_checked_values += 1
            try:
                is_valid_format = validator(value)
            except (TypeError, ValueError):
                is_valid_format = False
            if is_valid_format:
                format_valid_values += 1
                continue
            format_invalid_fields[field] += 1
            if field in fields_with_specific_flags:
                continue
            anomalies.append(
                anomaly(
                    config.name,
                    source_id_text,
                    "invalid_field_format",
                    field,
                    value,
                    "Present value does not match the expected source-specific format.",
                )
            )

        if not is_missing(source_id):
            ids[str(source_id)] += 1

        name = values.get("name", values.get("restaurant_name"))
        address = values.get("address")
        normalized_name = normalize_text(name)
        normalized_address = normalize_text(address)
        normalized_key = (
            f"{normalized_name}|{normalized_address}"
            if normalized_name and normalized_address
            else ""
        )
        if normalized_key:
            name_address_keys[normalized_key] += 1

        for field in config.critical_fields:
            if is_missing(values.get(field)):
                anomalies.append(
                    anomaly(
                        config.name,
                        source_id_text,
                        "missing_critical_field",
                        field,
                        "",
                        (
                            "Critical field is missing after source-specific "
                            "missing-value normalization."
                        ),
                    )
                )

        record_timestamps = []
        for field in config.timestamp_fields:
            timestamp_value = values.get(field)
            if is_missing(timestamp_value):
                continue
            timestamp_present_counts[field] += 1
            parsed_timestamp = parse_datetime(timestamp_value)
            if parsed_timestamp is None:
                anomalies.append(
                    anomaly(
                        config.name,
                        source_id_text,
                        "invalid_timestamp",
                        field,
                        timestamp_value,
                        "Timestamp is present but cannot be parsed as ISO-like datetime.",
                    )
                )
            else:
                timestamp_parseable_counts[field] += 1
                record_timestamps.append(parsed_timestamp)
        if record_timestamps:
            records_with_timestamp += 1
            timestamp_values.extend(record_timestamps)

        rating_raw = values.get(config.rating_field)
        rating = parse_float(rating_raw)
        if rating is not None:
            if 0 <= rating <= config.rating_scale:
                rating_values.append(rating)
            else:
                anomalies.append(
                    anomaly(
                        config.name,
                        source_id_text,
                        "invalid_rating",
                        config.rating_field,
                        values.get(config.rating_field),
                        f"Expected rating in [0, {config.rating_scale}].",
                    )
                )
        elif not is_missing(rating_raw):
            anomalies.append(
                anomaly(
                    config.name,
                    source_id_text,
                    "unparseable_rating",
                    config.rating_field,
                    rating_raw,
                    "Rating is present but cannot be parsed as a number.",
                )
            )

        review_count_raw = values.get(config.review_count_field)
        review_count = parse_int(review_count_raw)
        if review_count is not None:
            if review_count >= 0:
                review_values.append(review_count)
                if review_count == 0:
                    anomalies.append(
                        anomaly(
                            config.name,
                            source_id_text,
                            "zero_reviews",
                            config.review_count_field,
                            review_count,
                            "No reviews available.",
                        )
                    )
                elif review_count < low_review_threshold:
                    anomalies.append(
                        anomaly(
                            config.name,
                            source_id_text,
                            "low_review_count",
                            config.review_count_field,
                            review_count,
                            (
                                f"Review count is below {low_review_threshold}; "
                                "ratings are less reliable."
                            ),
                        )
                    )
            else:
                anomalies.append(
                    anomaly(
                        config.name,
                        source_id_text,
                        "invalid_review_count",
                        config.review_count_field,
                        values.get(config.review_count_field),
                        "Expected a non-negative integer.",
                    )
                )
        elif not is_missing(review_count_raw):
            anomalies.append(
                anomaly(
                    config.name,
                    source_id_text,
                    "unparseable_review_count",
                    config.review_count_field,
                    review_count_raw,
                    "Review count is present but cannot be parsed as an integer.",
                )
            )

        latitude = parse_float(values.get(config.latitude_field))
        longitude = parse_float(values.get(config.longitude_field))
        if latitude is not None or longitude is not None:
            coordinates_present += 1
            if latitude is not None and longitude is not None:
                valid_coordinates += 1
                if in_milan_area(latitude, longitude):
                    coordinates_in_area += 1
                else:
                    anomalies.append(
                        anomaly(
                            config.name,
                            source_id_text,
                            "coordinate_out_of_milan_area",
                            "latitude,longitude",
                            f"{latitude},{longitude}",
                            "Coordinate is outside the broad Milan-area bounding box.",
                        )
                    )
            else:
                anomalies.append(
                    anomaly(
                        config.name,
                        source_id_text,
                        "incomplete_coordinate_pair",
                        "latitude,longitude",
                        f"{latitude},{longitude}",
                        "Only one coordinate component is available.",
                    )
                )

        record_summaries.append(
            {
                "record_id": source_id_text,
                "name": name,
                "address": address,
                "normalized_name_address": normalized_key,
            }
        )

    duplicate_ids = {item: count for item, count in ids.items() if count > 1}
    duplicate_name_address = {item: count for item, count in name_address_keys.items() if count > 1}
    for record in record_summaries:
        record_id = record["record_id"]
        if record_id in duplicate_ids:
            anomalies.append(
                anomaly(
                    config.name,
                    record_id,
                    "duplicate_source_identifier",
                    config.id_field,
                    record_id,
                    "Source identifier is not unique.",
                )
            )
        key = record["normalized_name_address"]
        if key in duplicate_name_address:
            anomalies.append(
                anomaly(
                    config.name,
                    record_id,
                    "possible_duplicate_name_address",
                    "name,address",
                    key,
                    "Normalized name+address appears more than once; inspect before deduplication.",
                )
            )

    field_coverage = []
    for field in config.fields:
        present = present_counts[field]
        missing = record_count - present
        field_coverage.append(
            {
                "source": config.name,
                "field": field,
                "present": present,
                "missing": missing,
                "coverage_pct": pct(present, record_count),
            }
        )

    completeness_score = round(
        sum(row["coverage_pct"] for row in field_coverage) / len(field_coverage), 2
    ) if field_coverage else 0.0
    critical_rows = [row for row in field_coverage if row["field"] in config.critical_fields]
    critical_completeness_score = round(
        sum(row["coverage_pct"] for row in critical_rows) / len(critical_rows), 2
    ) if critical_rows else 0.0

    rating_valid_pct = pct(len(rating_values), record_count)
    review_valid_pct = pct(len(review_values), record_count)
    coordinate_valid_pct = pct(valid_coordinates, record_count)
    coordinate_in_area_pct = pct(coordinates_in_area, valid_coordinates)
    low_reviews = sum(1 for value in review_values if 0 < value < low_review_threshold)
    zero_reviews = sum(1 for value in review_values if value == 0)
    reliable_reviews = sum(1 for value in review_values if value >= low_review_threshold)
    duplicate_identifier_count = sum(count - 1 for count in duplicate_ids.values())
    duplicate_name_address_count = sum(count - 1 for count in duplicate_name_address.values())
    uniqueness_score = max(
        0.0,
        100.0 - pct(duplicate_identifier_count + duplicate_name_address_count, record_count),
    )
    timestamp_present_total = sum(timestamp_present_counts.values())
    timestamp_parseable_total = sum(timestamp_parseable_counts.values())
    timestamp_coverage_pct = pct(records_with_timestamp, record_count)
    timestamp_parseable_pct = pct(timestamp_parseable_total, timestamp_present_total)
    latest_timestamp = max(timestamp_values) if timestamp_values else None
    oldest_timestamp = min(timestamp_values) if timestamp_values else None
    timestamp_window_hours = (
        round((latest_timestamp - oldest_timestamp).total_seconds() / 3600, 2)
        if latest_timestamp and oldest_timestamp
        else None
    )
    collection_duration_hours = config.collection_duration_hours
    collection_duration_source = config.collection_duration_source
    if collection_duration_hours is None:
        collection_duration_hours = timestamp_window_hours
        collection_duration_source = (
            "observed timestamp window" if timestamp_window_hours is not None else "unavailable"
        )
    timeliness_score = refreshability_score(
        collection_duration_hours,
        config.refresh_target_hours,
    )
    data_age_days = (
        round((generated_at - latest_timestamp).total_seconds() / 86400, 2)
        if latest_timestamp
        else None
    )
    reliability_score = pct(reliable_reviews, record_count)
    validity_score = pct(format_valid_values, format_checked_values)
    spatial_readiness_score = coordinate_valid_pct
    overall_quality_score = weighted_quality_score(
        {
            "critical_completeness": critical_completeness_score,
            "validity": validity_score,
            "spatial_readiness": spatial_readiness_score,
            "uniqueness": uniqueness_score,
            "timeliness": timeliness_score,
            "reliability": reliability_score,
        }
    )

    return {
        "source": config.name,
        "input_path": str(config.path),
        "generated_at": generated_at.isoformat(),
        "record_count": record_count,
        "invalid_json_lines": invalid_json_lines,
        "field_coverage": field_coverage,
        "summary": {
            "completeness_score_pct": completeness_score,
            "critical_completeness_score_pct": critical_completeness_score,
            "unique_identifier_count": len(ids),
            "duplicate_identifier_count": duplicate_identifier_count,
            "possible_duplicate_name_address_count": duplicate_name_address_count,
            "uniqueness_score_pct": round(uniqueness_score, 2),
            "rating_scale": config.rating_scale,
            "valid_rating_count": len(rating_values),
            "valid_rating_pct": rating_valid_pct,
            "rating_min": min(rating_values) if rating_values else None,
            "rating_max": max(rating_values) if rating_values else None,
            "rating_avg": (
                round(sum(rating_values) / len(rating_values), 3) if rating_values else None
            ),
            "valid_review_count": len(review_values),
            "valid_review_count_pct": review_valid_pct,
            "review_count_min": min(review_values) if review_values else None,
            "review_count_max": max(review_values) if review_values else None,
            "review_count_avg": (
                round(sum(review_values) / len(review_values), 1) if review_values else None
            ),
            "zero_review_records": zero_reviews,
            "low_review_threshold": low_review_threshold,
            "low_review_records": low_reviews,
            "low_review_pct_of_valid_reviews": pct(low_reviews, len(review_values)),
            "reliable_review_records": reliable_reviews,
            "reliability_score_pct": reliability_score,
            "coordinates_present_count": coordinates_present,
            "valid_coordinate_pair_count": valid_coordinates,
            "valid_coordinate_pair_pct": coordinate_valid_pct,
            "coordinates_in_milan_area_count": coordinates_in_area,
            "coordinates_in_milan_area_pct": coordinate_in_area_pct,
            "spatial_readiness_score_pct": spatial_readiness_score,
            "timestamp_field_count": len(config.timestamp_fields),
            "timestamp_present_count": timestamp_present_total,
            "timestamp_parseable_count": timestamp_parseable_total,
            "records_with_timestamp_count": records_with_timestamp,
            "timestamp_coverage_pct": timestamp_coverage_pct,
            "timestamp_parseable_pct": timestamp_parseable_pct,
            "timestamp_window_hours": timestamp_window_hours,
            "collection_duration_hours": (
                round(collection_duration_hours, 2)
                if collection_duration_hours is not None
                else None
            ),
            "collection_duration_source": collection_duration_source,
            "refresh_target_hours": config.refresh_target_hours,
            "timeliness_score_pct": timeliness_score,
            "oldest_timestamp": oldest_timestamp.isoformat() if oldest_timestamp else None,
            "latest_timestamp": latest_timestamp.isoformat() if latest_timestamp else None,
            "data_age_days": data_age_days,
            "format_checked_value_count": format_checked_values,
            "format_valid_value_count": format_valid_values,
            "format_invalid_value_count": format_checked_values - format_valid_values,
            "format_invalid_fields": dict(format_invalid_fields),
            "validity_score_pct": validity_score,
            "overall_quality_score_pct": overall_quality_score,
            "anomaly_count": len(anomalies),
        },
        "anomalies": anomalies,
    }


def run_assessment(
    google_path: Path,
    tripadvisor_path: Path,
    thefork_path: Path,
    output_dir: Path,
    low_review_threshold: int = 20,
) -> dict[str, Any]:
    configs = [
        google_config(google_path),
        tripadvisor_config(tripadvisor_path),
        thefork_config(thefork_path),
    ]
    sources = [analyze_source(config, low_review_threshold) for config in configs]
    anomalies = [item for source in sources for item in source["anomalies"]]
    for source in sources:
        source["summary"]["anomaly_count"] = len(source["anomalies"])
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "low_review_threshold": low_review_threshold,
        "sources": sources,
    }
    write_outputs(payload, anomalies, output_dir)
    return payload


def write_outputs(
    payload: dict[str, Any], anomalies: list[dict[str, Any]], output_dir: Path
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "source_quality_metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    coverage_rows = [row for source in payload["sources"] for row in source["field_coverage"]]
    score_rows = [quality_score_row(source) for source in payload["sources"]]
    write_csv(output_dir / "field_coverage.csv", coverage_rows, COVERAGE_FIELDNAMES)
    write_csv(output_dir / "source_quality_scores.csv", score_rows, SCORE_FIELDNAMES)
    write_csv(output_dir / "anomalies.csv", anomalies, ANOMALY_FIELDNAMES)


def quality_score_row(source: dict[str, Any]) -> dict[str, Any]:
    summary = source["summary"]
    return {
        "source": source["source"],
        "overall_quality_score_pct": summary["overall_quality_score_pct"],
        "completeness_score_pct": summary["completeness_score_pct"],
        "critical_completeness_score_pct": summary["critical_completeness_score_pct"],
        "validity_score_pct": summary["validity_score_pct"],
        "spatial_readiness_score_pct": summary["spatial_readiness_score_pct"],
        "uniqueness_score_pct": summary["uniqueness_score_pct"],
        "timeliness_score_pct": summary["timeliness_score_pct"],
        "timestamp_coverage_pct": summary["timestamp_coverage_pct"],
        "collection_duration_hours": summary["collection_duration_hours"],
        "refresh_target_hours": summary["refresh_target_hours"],
        "reliability_score_pct": summary["reliability_score_pct"],
        "anomaly_count": summary["anomaly_count"],
        "record_count": source["record_count"],
    }


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str] | None = None,
) -> None:
    fieldnames = fieldnames or (list(rows[0].keys()) if rows else [])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
        writer.writerows(rows)


def anomaly(
    source: str,
    record_id: str,
    issue_type: str,
    field: str,
    value: Any,
    detail: str,
) -> dict[str, Any]:
    return {
        "source": source,
        "record_id": record_id,
        "issue_type": issue_type,
        "field": field,
        "value": "" if value is None else str(value),
        "detail": detail,
    }


def pct(numerator: int, denominator: int) -> float:
    if not denominator:
        return 0.0
    value = round((numerator / denominator) * 100, 2)
    if numerator < denominator and value == 100.0:
        return 99.99
    return value


def average_pct(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def refreshability_score(duration_hours: float | None, target_hours: float) -> float:
    if duration_hours is None or target_hours <= 0:
        return 0.0
    return round(max(0.0, 100.0 * (1 - (duration_hours / target_hours))), 2)


def weighted_quality_score(components: dict[str, float]) -> float:
    weights = {
        "critical_completeness": 0.25,
        "validity": 0.20,
        "spatial_readiness": 0.15,
        "uniqueness": 0.15,
        "timeliness": 0.10,
        "reliability": 0.15,
    }
    return round(sum(components[name] * weight for name, weight in weights.items()), 2)


def parse_datetime(value: Any) -> datetime | None:
    if is_missing(value):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
