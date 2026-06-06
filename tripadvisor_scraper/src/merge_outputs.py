from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge Tripadvisor scraper JSON outputs, keeping the richest record for each restaurant."
    )
    parser.add_argument("inputs", nargs="+", help="Input JSON files to merge.")
    parser.add_argument("--output", required=True, help="Merged JSON output path.")
    parser.add_argument("--report", default=None, help="Optional merge audit report JSON path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_paths = [Path(path) for path in args.inputs]
    output_path = Path(args.output)
    report_path = Path(args.report) if args.report else output_path.with_suffix(".merge_report.json")

    merged_by_key: dict[str, dict[str, Any]] = {}
    source_by_key: dict[str, str] = {}
    input_reports = []
    replacement_reasons: dict[str, int] = {}

    for input_path in input_paths:
        records = load_records(input_path)
        input_reports.append(build_stats(input_path, records))
        for record in records:
            key = merge_key(record)
            current = merged_by_key.get(key)
            if current is None:
                merged_by_key[key] = record
                source_by_key[key] = str(input_path)
                continue

            chosen, reason = choose_record(current, record)
            if chosen is record:
                merged_by_key[key] = record
                source_by_key[key] = str(input_path)
                replacement_reasons[reason] = replacement_reasons.get(reason, 0) + 1

    merged_records = list(merged_by_key.values())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, merged_records)

    report = {
        "inputs": input_reports,
        "output": build_stats(output_path, merged_records),
        "replacement_reasons": replacement_reasons,
        "chosen_sources": summarize_sources(source_by_key),
    }
    write_json(report_path, report)

    print(f"Merged {len(merged_records)} Tripadvisor records into {output_path}")
    print(f"Merge report written to {report_path}")


def load_records(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as input_file:
        payload = json.load(input_file)
    if not isinstance(payload, list):
        raise ValueError(f"{path} does not contain a JSON list.")
    records = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{path} item {index} is not a JSON object.")
        records.append(item)
    return records


def write_json(path: Path, payload: Any) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    temporary_path.replace(path)


def merge_key(record: dict[str, Any]) -> str:
    restaurant_url = normalize_url(record.get("restaurant_url"))
    if restaurant_url:
        return f"url:{restaurant_url}"
    source_id = clean_text(record.get("source_id"))
    if source_id:
        return f"source_id:{source_id}"
    name = clean_text(record.get("restaurant_name") or record.get("name")).lower()
    address = clean_text(record.get("address")).lower()
    if name or address:
        return f"name_address:{name}|{address}"
    raise ValueError(f"Record has no stable merge key: {record}")


def normalize_url(value: Any) -> str:
    url = clean_text(value)
    if not url:
        return ""
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def choose_record(current: dict[str, Any], candidate: dict[str, Any]) -> tuple[dict[str, Any], str]:
    current_detail = current.get("detail_scraped") is True
    candidate_detail = candidate.get("detail_scraped") is True
    if candidate_detail and not current_detail:
        return candidate, "candidate_has_detail"
    if current_detail and not candidate_detail:
        return current, "current_has_detail"

    current_score = richness_score(current)
    candidate_score = richness_score(candidate)
    if candidate_score > current_score:
        return candidate, "candidate_richer"
    return current, "current_richer_or_equal"


def richness_score(record: dict[str, Any]) -> int:
    score = 0
    for key, value in record.items():
        if is_non_empty(value):
            score += field_weight(key, value)
    return score


def field_weight(key: str, value: Any) -> int:
    if key == "detail_scraped" and value is True:
        return 10
    if key == "reviews" and isinstance(value, list):
        return 2 + len(value)
    if key == "social_links" and isinstance(value, dict):
        return 2 + len(value)
    if key in {"website", "phone", "phone_number", "email", "opening_hours", "working_days_hours", "working_hours_structured"}:
        return 3
    if key in {"latitude", "longitude"}:
        return 4
    return 1


def is_non_empty(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (list, dict)) and not value:
        return False
    return True


def build_stats(path: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "path": str(path),
        "records": len(records),
        "detail_scraped": count_with(records, "detail_scraped", True),
        "with_coordinates": sum(
            1 for record in records if is_non_empty(record.get("latitude")) and is_non_empty(record.get("longitude"))
        ),
        "with_reviews": sum(1 for record in records if is_non_empty(record.get("reviews"))),
        "with_website": sum(1 for record in records if is_non_empty(record.get("website"))),
        "with_social_links": sum(1 for record in records if is_non_empty(record.get("social_links"))),
        "with_phone": sum(1 for record in records if is_non_empty(record.get("phone_number") or record.get("phone"))),
        "with_email": sum(1 for record in records if is_non_empty(record.get("email"))),
        "with_working_hours_structured": sum(1 for record in records if is_non_empty(record.get("working_hours_structured"))),
        "avg_richness_score": round(
            sum(richness_score(record) for record in records) / max(1, len(records)),
            2,
        ),
    }


def count_with(records: list[dict[str, Any]], key: str, expected_value: Any) -> int:
    return sum(1 for record in records if record.get(key) == expected_value)


def summarize_sources(source_by_key: dict[str, str]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for source in source_by_key.values():
        summary[source] = summary.get(source, 0) + 1
    return summary


if __name__ == "__main__":
    main()
