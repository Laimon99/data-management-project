from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pymongo import MongoClient

MONGO_URI = os.environ.get("DATAMAN_MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("DATAMAN_MONGO_DB", "dataman")

COLLECTIONS = [
    "restaurants_clean_google",
    "restaurants_clean_tripadvisor",
    "restaurants_clean_thefork",
]

DEFAULT_OUTPUT_PATH = Path("mongo_schema_audit.json")


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "obj"
    if isinstance(value, (datetime, date)):
        return "datetime"
    return type(value).__name__


def is_non_empty(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (list, dict)) and len(value) == 0:
        return False
    return True


def pct(count: int, total: int) -> float:
    return round(count / total * 100, 1) if total else 0.0


def audit_collection(db: Any, collection_name: str) -> dict[str, Any]:
    collection = db[collection_name]
    total = collection.count_documents({})
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"present": 0, "non_null": 0, "non_empty": 0, "types": set()}
    )

    for doc in collection.find({}):
        for field, value in doc.items():
            stats[field]["present"] += 1
            if value is not None:
                stats[field]["non_null"] += 1
            if is_non_empty(value):
                stats[field]["non_empty"] += 1
            stats[field]["types"].add(type_name(value))

    return {
        "documents": total,
        "fields": {
            field: {
                "present": data["present"],
                "present_pct": pct(data["present"], total),
                "non_null": data["non_null"],
                "non_null_pct": pct(data["non_null"], total),
                "non_empty": data["non_empty"],
                "non_empty_pct": pct(data["non_empty"], total),
                "types": sorted(data["types"]),
            }
            for field, data in sorted(stats.items())
        },
    }


def main() -> None:
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    report = {
        collection_name: audit_collection(db, collection_name) for collection_name in COLLECTIONS
    }
    output = json.dumps(report, indent=2, default=str, ensure_ascii=False)

    if "--stdout" in sys.argv:
        print(output)
        return

    output_path = DEFAULT_OUTPUT_PATH
    if "--output" in sys.argv:
        try:
            output_path = Path(sys.argv[sys.argv.index("--output") + 1])
        except IndexError as exc:
            raise SystemExit("--output requires a path") from exc

    output_path.write_text(output + "\n", encoding="utf-8")
    summary = {
        collection: {
            "documents": data["documents"],
            "field_count": len(data["fields"]),
        }
        for collection, data in report.items()
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
