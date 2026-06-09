#!/usr/bin/env python3
"""Export the clean Mongo datasets and ER candidates to large JSON files."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bson import json_util
from pymongo import MongoClient
from pymongo.errors import PyMongoError

DEFAULT_COLLECTIONS = (
    "restaurants_clean_google",
    "restaurants_clean_tripadvisor",
    "restaurants_clean_thefork",
    "entity_resolution_candidates",
)
DEFAULT_OUTPUT_DIR = Path("data/exports/mongo_json")


@dataclass(frozen=True)
class ExportResult:
    collection: str
    output_file: str
    document_count: int


def _json_default(value: Any) -> Any:
    """Serialize Mongo-native values such as ObjectId and datetime."""
    return json.loads(json_util.dumps(value))


def export_collection(
    collection: Any,
    output_file: Path,
    *,
    batch_size: int = 1000,
) -> ExportResult:
    """Stream one Mongo collection as a single JSON array file."""
    output_file.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    cursor = collection.find({}, batch_size=batch_size)
    with output_file.open("w", encoding="utf-8") as handle:
        handle.write("[\n")
        for doc in cursor:
            if count:
                handle.write(",\n")
            handle.write(json.dumps(doc, ensure_ascii=False, default=_json_default))
            count += 1
        handle.write("\n]\n")

    return ExportResult(
        collection=collection.name,
        output_file=str(output_file),
        document_count=count,
    )


def write_manifest(output_dir: Path, results: Iterable[ExportResult]) -> Path:
    manifest_path = output_dir / "manifest.json"
    payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "collections": [asdict(result) for result in results],
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export the three clean restaurant datasets and the entity-resolution "
            "candidate pairs collection from MongoDB to large JSON array files."
        )
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("DATAMAN_MONGO_URI", "mongodb://localhost:27017"),
        help="MongoDB URI. Defaults to DATAMAN_MONGO_URI or mongodb://localhost:27017.",
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("DATAMAN_MONGO_DB", "dataman"),
        help="Mongo database name. Defaults to DATAMAN_MONGO_DB or dataman.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for exported JSON files. Defaults to {DEFAULT_OUTPUT_DIR}.",
    )
    parser.add_argument(
        "--collection",
        action="append",
        dest="collections",
        help=(
            "Collection to export. Repeat to override the default four collections. "
            "Default: restaurants_clean_google, restaurants_clean_tripadvisor, "
            "restaurants_clean_thefork, entity_resolution_candidates."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Mongo cursor batch size. Defaults to 1000.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    collections = tuple(args.collections or DEFAULT_COLLECTIONS)

    client: MongoClient[Any] = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
        db = client[args.db]
        results = [
            export_collection(
                db[collection_name],
                args.output_dir / f"{collection_name}.json",
                batch_size=args.batch_size,
            )
            for collection_name in collections
        ]
    except PyMongoError as exc:
        print(f"MongoDB error: {exc}", flush=True)
        return 1
    finally:
        client.close()

    manifest_path = write_manifest(args.output_dir, results)
    for result in results:
        print(f"{result.collection}: {result.document_count} docs -> {result.output_file}")
    print(f"manifest -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
