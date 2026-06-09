from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from transform.entity_resolution.scoring import MATCH, NON_MATCH

GOLD_LABELS = {MATCH, NON_MATCH}


def _normalized_label(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalized_id(value: Any) -> str:
    return str(value or "").strip()


def load_gold_rows(paths: list[Path]) -> list[dict[str, str]]:
    """Load labeled gold CSVs, deduplicating by candidate `_id`.

    Later files win, and later rows inside the same file win. This lets an expanded
    hand-label file override older calibration labels without editing the original CSVs.
    """
    by_id: dict[str, dict[str, str]] = {}
    for path in paths:
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                candidate_id = _normalized_id(row.get("_id"))
                human_label = _normalized_label(row.get("human_label"))
                if not candidate_id or human_label not in GOLD_LABELS:
                    continue
                normalized = {str(key): str(value or "") for key, value in row.items()}
                normalized["_id"] = candidate_id
                normalized["human_label"] = human_label
                normalized["gold_path"] = str(path)
                by_id[candidate_id] = normalized
    return list(by_id.values())


def gold_ids(rows: list[dict[str, str]]) -> set[str]:
    return {row["_id"] for row in rows if row.get("_id")}
