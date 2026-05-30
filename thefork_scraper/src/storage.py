from __future__ import annotations

import json
import logging
from pathlib import Path

from .models import RestaurantRecord


class JsonStorage:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.final_path = output_dir / "thefork_milan_restaurants_normalized.json"
        self.partial_path = output_dir / "thefork_milan_restaurants_normalized_partial.json"

    def save_partial(self, records: list[RestaurantRecord]) -> None:
        self._save(records, self.partial_path)
        logging.info("Saved partial output with %s records to %s", len(records), self.partial_path)

    def save_final(self, records: list[RestaurantRecord]) -> None:
        self._save(records, self.final_path)
        logging.info("Saved final output with %s records to %s", len(records), self.final_path)

    def _save(self, records: list[RestaurantRecord], path: Path) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        payload = [record.to_dict() for record in records]
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        with temporary_path.open("w", encoding="utf-8") as output_file:
            json.dump(payload, output_file, ensure_ascii=False, indent=2)
            output_file.write("\n")
        temporary_path.replace(path)

