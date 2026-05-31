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
        self.validation_report_path = output_dir / "thefork_milan_validation_report.json"
        self.proxy_progress_report_path = output_dir / "thefork_proxy_progress_report.json"

    def save_partial(self, records: list[RestaurantRecord]) -> None:
        self._save(records, self.partial_path)
        logging.info("Saved partial output with %s records to %s", len(records), self.partial_path)

    def save_final(self, records: list[RestaurantRecord]) -> None:
        self._save(records, self.final_path)
        logging.info("Saved final output with %s records to %s", len(records), self.final_path)

    def save_validation_report(self, report: dict) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = self.validation_report_path.with_suffix(self.validation_report_path.suffix + ".tmp")
        with temporary_path.open("w", encoding="utf-8") as output_file:
            json.dump(report, output_file, ensure_ascii=False, indent=2)
            output_file.write("\n")
        temporary_path.replace(self.validation_report_path)
        logging.info("Saved validation report to %s", self.validation_report_path)

    def save_proxy_progress_report(self, report: dict) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = self.proxy_progress_report_path.with_suffix(self.proxy_progress_report_path.suffix + ".tmp")
        with temporary_path.open("w", encoding="utf-8") as output_file:
            json.dump(report, output_file, ensure_ascii=False, indent=2)
            output_file.write("\n")
        temporary_path.replace(self.proxy_progress_report_path)
        logging.info("Saved proxy progress report to %s", self.proxy_progress_report_path)

    def load_partial(self) -> list[RestaurantRecord]:
        if not self.partial_path.exists():
            return []
        with self.partial_path.open("r", encoding="utf-8") as input_file:
            payload = json.load(input_file)
        records = [RestaurantRecord(**item) for item in payload]
        logging.info("Loaded %s records from partial output %s", len(records), self.partial_path)
        return records

    def _save(self, records: list[RestaurantRecord], path: Path) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        payload = [record.to_dict() for record in records]
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        with temporary_path.open("w", encoding="utf-8") as output_file:
            json.dump(payload, output_file, ensure_ascii=False, indent=2)
            output_file.write("\n")
        temporary_path.replace(path)
