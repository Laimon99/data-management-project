from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "services"
if str(SERVICES) not in sys.path:
    sys.path.insert(0, str(SERVICES))

from transform.entity_resolution.config import ERSettings  # noqa: E402


def _chain_bucket(value: Any) -> str:
    if value is True:
        return "chain"
    if value is False:
        return "non_chain"
    return "missing_is_chain"


def _threshold_distribution(
    threshold_counts: Counter[tuple[str, str, float | None, float | None]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    distribution: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    def sort_key(
        item: tuple[tuple[str, str, float | None, float | None], int],
    ) -> tuple[str, str, float, float]:
        source, chain_bucket, dmin, dmax = item[0]
        return (
            source,
            chain_bucket,
            -1.0 if dmin is None else dmin,
            -1.0 if dmax is None else dmax,
        )

    for (source, chain_bucket, dmin, dmax), count in sorted(
        threshold_counts.items(),
        key=sort_key,
    ):
        distribution[source][chain_bucket].append(
            {
                "dmin": dmin,
                "dmax": dmax,
                "count": count,
            }
        )
    return {
        source: dict(sorted(chain_buckets.items()))
        for source, chain_buckets in sorted(distribution.items())
    }


def main() -> None:
    settings = ERSettings()
    collection = MongoClient(settings.mongo_uri)[settings.mongo_db][settings.destination_collection]
    server_total = collection.count_documents({})
    server_non_geo = collection.count_documents({"block_source": {"$ne": "geo"}})
    server_missing_thresholds = collection.count_documents(
        {"$or": [{"dmin": {"$exists": False}}, {"dmax": {"$exists": False}}]}
    )

    docs = list(
        collection.find(
            {},
            {
                "_id": 1,
                "source": 1,
                "label": 1,
                "block_source": 1,
                "is_chain": 1,
                "chain_brand": 1,
                "chain_hardening": 1,
                "dmin": 1,
                "dmax": 1,
            },
        )
    )

    by_source = Counter(str(doc.get("source")) for doc in docs)
    by_label = Counter(str(doc.get("label")) for doc in docs)
    by_block_source = Counter(str(doc.get("block_source")) for doc in docs)
    by_chain_bucket = Counter(_chain_bucket(doc.get("is_chain")) for doc in docs)
    chain_brands = Counter(
        str(doc.get("chain_brand"))
        for doc in docs
        if doc.get("is_chain") is True and doc.get("chain_brand")
    )
    source_chain_counts: dict[str, Counter[str]] = defaultdict(Counter)
    source_label_counts: dict[str, Counter[str]] = defaultdict(Counter)
    threshold_counts: Counter[tuple[str, str, float | None, float | None]] = Counter()
    for doc in docs:
        source = str(doc.get("source"))
        chain_bucket = _chain_bucket(doc.get("is_chain"))
        source_chain_counts[source][chain_bucket] += 1
        source_label_counts[source][str(doc.get("label"))] += 1
        threshold_counts[
            (
                source,
                chain_bucket,
                doc.get("dmin"),
                doc.get("dmax"),
            )
        ] += 1

    result = {
        "database": settings.mongo_db,
        "collection": settings.destination_collection,
        "server_total": server_total,
        "server_non_geo": server_non_geo,
        "server_missing_thresholds": server_missing_thresholds,
        "threshold_counts_by_source_chain": _threshold_distribution(threshold_counts),
        "total": len(docs),
        "by_source": dict(sorted(by_source.items())),
        "by_label": dict(sorted(by_label.items())),
        "by_block_source": dict(sorted(by_block_source.items())),
        "by_chain_bucket": dict(sorted(by_chain_bucket.items())),
        "source_chain_counts": {
            source: dict(sorted(counts.items()))
            for source, counts in sorted(source_chain_counts.items())
        },
        "source_label_counts": {
            source: dict(sorted(counts.items()))
            for source, counts in sorted(source_label_counts.items())
        },
        "top_chain_brands": dict(chain_brands.most_common(25)),
        "chain_hardened": sum(1 for doc in docs if doc.get("chain_hardening")),
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
