from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


BAD_STRINGS = {
    "",
    "-",
    "--",
    "[]",
    "{}",
    "na",
    "n/a",
    "nan",
    "none",
    "null",
    "not available",
    "not found",
    "non disponibile",
}

FIELD_ALIASES = {
    "restaurant_name": ("restaurant_name", "name"),
    "restaurant_url": ("restaurant_url", "source_url", "url"),
    "source_id": ("source_id", "restaurant_id"),
    "address": ("address",),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lng", "lon"),
    "rating": ("rating",),
    "review_count": ("review_count", "total_review", "reviews_count"),
    "cuisine_type": ("cuisine_type", "cuisine", "cuisines"),
    "price_range": ("price_range", "price_level", "price"),
    "photo_count": ("photo_count", "number_photo_uploaded"),
    "website": ("website",),
    "phone_number": ("phone_number", "phone"),
    "email": ("email",),
    "working_days_hours": ("working_days_hours", "opening_hours"),
    "review_snippets": ("review_snippets",),
    "reviews": ("reviews", "review"),
    "detail_scraped": ("detail_scraped",),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Tripadvisor dataset quality without modifying either file.")
    parser.add_argument("--new", required=True, help="New normalized Tripadvisor JSON.")
    parser.add_argument("--legacy", required=True, help="Legacy Tripadvisor JSON to compare against.")
    parser.add_argument("--output", default=None, help="Optional JSON report path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    new_path = Path(args.new)
    legacy_path = Path(args.legacy)
    output_path = Path(args.output) if args.output else new_path.with_suffix(".quality_compare_report.json")

    new_records = load_records(new_path)
    legacy_records = load_records(legacy_path)
    report = compare_datasets(new_records, legacy_records, new_path, legacy_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, report)
    print_summary(report)
    print(f"Quality comparison report written to {output_path}")


def load_records(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as input_file:
        payload = json.load(input_file)
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = next(
            (value for key, value in payload.items() if key in {"restaurants", "data", "items", "results"} and isinstance(value, list)),
            None,
        )
        if records is None:
            raise ValueError(f"{path} does not contain a recognizable records list.")
    else:
        raise ValueError(f"{path} does not contain a JSON list or object.")

    if not all(isinstance(record, dict) for record in records):
        raise ValueError(f"{path} contains non-object records.")
    return records


def compare_datasets(
    new_records: list[dict[str, Any]],
    legacy_records: list[dict[str, Any]],
    new_path: Path,
    legacy_path: Path,
) -> dict[str, Any]:
    new_stats = build_stats(new_records)
    legacy_stats = build_stats(legacy_records)

    comparable_fields = sorted(FIELD_ALIASES)
    field_deltas = {
        field: {
            "new_non_null": new_stats["field_coverage"][field]["non_null"],
            "legacy_non_null": legacy_stats["field_coverage"][field]["non_null"],
            "delta": new_stats["field_coverage"][field]["non_null"] - legacy_stats["field_coverage"][field]["non_null"],
        }
        for field in comparable_fields
    }

    return {
        "new_path": str(new_path),
        "legacy_path": str(legacy_path),
        "new": new_stats,
        "legacy": legacy_stats,
        "field_deltas": field_deltas,
        "overlap": build_overlap(new_records, legacy_records),
        "new_beats_legacy_on_fields": [
            field for field, delta in field_deltas.items() if delta["new_non_null"] > delta["legacy_non_null"]
        ],
        "legacy_beats_new_on_fields": [
            field for field, delta in field_deltas.items() if delta["legacy_non_null"] > delta["new_non_null"]
        ],
    }


def build_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    field_coverage = {}
    for canonical_field in FIELD_ALIASES:
        non_null = sum(1 for record in records if has_canonical_value(record, canonical_field))
        field_coverage[canonical_field] = {
            "non_null": non_null,
            "null": len(records) - non_null,
            "coverage_pct": round((non_null / len(records)) * 100, 2) if records else 0.0,
        }

    source_ids = [source_id_for_record(record) for record in records if source_id_for_record(record)]
    urls = [canonical_value(record, "restaurant_url") for record in records if is_meaningful(canonical_value(record, "restaurant_url"))]
    names = [normalize_name(canonical_value(record, "restaurant_name")) for record in records if is_meaningful(canonical_value(record, "restaurant_name"))]

    return {
        "total_records": len(records),
        "field_coverage": field_coverage,
        "source_ids_extractable": len(source_ids),
        "duplicate_source_ids": count_duplicate_excess(source_ids),
        "duplicate_urls": count_duplicate_excess(urls),
        "duplicate_names": count_duplicate_excess(names),
    }


def build_overlap(new_records: list[dict[str, Any]], legacy_records: list[dict[str, Any]]) -> dict[str, int]:
    new_ids = {source_id for record in new_records if (source_id := source_id_for_record(record))}
    legacy_ids = {source_id for record in legacy_records if (source_id := source_id_for_record(record))}
    new_names = {
        normalize_name(canonical_value(record, "restaurant_name"))
        for record in new_records
        if is_meaningful(canonical_value(record, "restaurant_name"))
    }
    legacy_names = {
        normalize_name(canonical_value(record, "restaurant_name"))
        for record in legacy_records
        if is_meaningful(canonical_value(record, "restaurant_name"))
    }

    return {
        "source_id_overlap": len(new_ids & legacy_ids),
        "new_source_ids": len(new_ids),
        "legacy_source_ids": len(legacy_ids),
        "new_source_ids_not_in_legacy": len(new_ids - legacy_ids),
        "legacy_source_ids_not_in_new": len(legacy_ids - new_ids),
        "name_overlap": len(new_names & legacy_names),
        "new_names": len(new_names),
        "legacy_names": len(legacy_names),
    }


def has_canonical_value(record: dict[str, Any], canonical_field: str) -> bool:
    if canonical_field == "detail_scraped":
        return canonical_value(record, canonical_field) is True
    value = canonical_value(record, canonical_field)
    if canonical_field == "source_id" and not is_meaningful(value):
        value = source_id_for_record(record)
    return is_meaningful(value)


def canonical_value(record: dict[str, Any], canonical_field: str) -> Any:
    for field_name in FIELD_ALIASES[canonical_field]:
        if field_name in record and is_meaningful(record[field_name]):
            return record[field_name]
    return None


def source_id_for_record(record: dict[str, Any]) -> str | None:
    explicit = canonical_value(record, "source_id")
    if is_meaningful(explicit):
        text = str(explicit).strip().lower()
        if re.fullmatch(r"d\d+", text):
            return text

    url = canonical_value(record, "restaurant_url")
    if not is_meaningful(url):
        return None
    match = re.search(r"-d(\d+)-", str(url), re.IGNORECASE)
    return f"d{match.group(1)}" if match else None


def is_meaningful(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        cleaned = value.strip().lower()
        return cleaned not in BAD_STRINGS and not cleaned.startswith("not found")
    if isinstance(value, list):
        return any(is_meaningful(item) for item in value)
    if isinstance(value, dict):
        return any(is_meaningful(item) for item in value.values())
    return True


def normalize_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def count_duplicate_excess(values: list[Any]) -> int:
    return sum(count - 1 for count in Counter(values).values() if count > 1)


def write_json(path: Path, payload: Any) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    temporary_path.replace(path)


def print_summary(report: dict[str, Any]) -> None:
    print("New records:", report["new"]["total_records"])
    print("Legacy records:", report["legacy"]["total_records"])
    print("Source ID overlap:", report["overlap"]["source_id_overlap"])
    print("New beats legacy on:", ", ".join(report["new_beats_legacy_on_fields"]) or "none")
    print("Legacy beats new on:", ", ".join(report["legacy_beats_new_on_fields"]) or "none")


if __name__ == "__main__":
    main()
