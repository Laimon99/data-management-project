from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge multiple TheFork JSON outputs, preferring completed detail records."
    )
    parser.add_argument("inputs", nargs="+", help="Input TheFork JSON files to merge.")
    parser.add_argument("--output", required=True, help="Output merged JSON path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    merged = merge_files([Path(item) for item in args.inputs])
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(merged, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    print(f"Merged {len(merged)} TheFork records into {output_path}")


def merge_files(paths: list[Path]) -> list[dict[str, Any]]:
    records_by_key: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []

    for path in paths:
        with path.open("r", encoding="utf-8-sig") as input_file:
            payload = json.load(input_file)
        if not isinstance(payload, list):
            raise ValueError(f"Expected a list of records in {path}")

        for record in payload:
            if not isinstance(record, dict):
                continue
            key = merge_key(record)
            if key not in records_by_key:
                records_by_key[key] = record
                ordered_keys.append(key)
                continue
            records_by_key[key] = choose_better_record(records_by_key[key], record)

    return [records_by_key[key] for key in ordered_keys]


def merge_key(record: dict[str, Any]) -> str:
    restaurant_url = record.get("restaurant_url")
    if isinstance(restaurant_url, str) and restaurant_url.strip():
        parsed = urlsplit(restaurant_url.strip())
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    source_id = record.get("source_id")
    if isinstance(source_id, str) and source_id.strip():
        return f"source_id:{source_id.strip()}"

    name = str(record.get("restaurant_name") or "").strip().casefold()
    address = str(record.get("address") or "").strip().casefold()
    return f"fallback:{name}|{address}"


def choose_better_record(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    current_complete = bool(current.get("detail_scraped"))
    candidate_complete = bool(candidate.get("detail_scraped"))
    if candidate_complete and not current_complete:
        return candidate
    if current_complete and not candidate_complete:
        return current
    if richness_score(candidate) > richness_score(current):
        return candidate
    return current


def richness_score(record: dict[str, Any]) -> int:
    score = 0
    for value in record.values():
        if value is None or value == "":
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        score += 1
    return score


if __name__ == "__main__":
    main()
