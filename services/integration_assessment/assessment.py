from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import IntegrationAssessmentSettings
from .er_metrics import CONFUSION_FIELDNAMES, ERROR_FIELDNAMES, compute_er_metrics
from .geo_metrics import GEOCODING_FIELDNAMES, compute_geo_metrics
from .gold import gold_ids, load_gold_rows
from .link_metrics import compute_link_metrics
from .mongo import IntegrationCollections, open_collections


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _json_default(value: Any) -> str:
    return str(value)


def _collection_docs(collection: Any) -> list[dict[str, Any]]:
    return list(collection.find({}))


def build_payload(
    *,
    settings: IntegrationAssessmentSettings,
    gold_rows: list[dict[str, str]],
    in_calibration_gold_rows: list[dict[str, str]] | None = None,
    evaluation_rows_after_csv_dedupe: int | None = None,
    excluded_evaluation_overlap: int = 0,
    candidates: list[dict[str, Any]],
    links: list[dict[str, Any]],
    integrated_docs: list[dict[str, Any]],
    google_docs: list[dict[str, Any]],
    tripadvisor_docs: list[dict[str, Any]],
) -> dict[str, Any]:
    er = compute_er_metrics(
        gold_rows,
        candidates,
        cv_gold_rows=in_calibration_gold_rows or gold_rows,
        cv_folds=settings.cv_folds,
        cv_seed=settings.cv_seed,
    )
    if in_calibration_gold_rows:
        er["calibration_in_sample"] = compute_er_metrics(
            in_calibration_gold_rows,
            candidates,
            cv_gold_rows=in_calibration_gold_rows,
            cv_folds=settings.cv_folds,
            cv_seed=settings.cv_seed,
        )["in_sample"]
    link = compute_link_metrics(gold_rows, candidates, links, integrated_docs)
    calibration_link = (
        compute_link_metrics(in_calibration_gold_rows, candidates, links, integrated_docs)
        if in_calibration_gold_rows
        else None
    )
    geo = compute_geo_metrics(
        gold_rows,
        candidates,
        links,
        google_docs,
        tripadvisor_docs,
        buckets_m=settings.distance_buckets_m,
    )
    calibration_geo = (
        compute_geo_metrics(
            in_calibration_gold_rows,
            candidates,
            links,
            google_docs,
            tripadvisor_docs,
            buckets_m=settings.distance_buckets_m,
        )
        if in_calibration_gold_rows
        else None
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "gold": {
            "rows": len(gold_rows),
            "sources": sorted(
                {row.get("gold_path", "") for row in gold_rows if row.get("gold_path")}
            ),
            "evaluation": {
                "rows": len(gold_rows),
                "rows_after_csv_dedupe": (
                    evaluation_rows_after_csv_dedupe
                    if evaluation_rows_after_csv_dedupe is not None
                    else len(gold_rows)
                ),
                "sources": sorted(
                    {row.get("gold_path", "") for row in gold_rows if row.get("gold_path")}
                ),
                "excluded_overlap_with_in_calibration": excluded_evaluation_overlap,
            },
            "in_calibration": {
                "rows": len(in_calibration_gold_rows or []),
                "sources": sorted(
                    {
                        row.get("gold_path", "")
                        for row in (in_calibration_gold_rows or [])
                        if row.get("gold_path")
                    }
                ),
            },
        },
        "mongo_counts": {
            "candidates": len(candidates),
            "links": len(links),
            "integrated": len(integrated_docs),
            "google_clean": len(google_docs),
            "tripadvisor_clean": len(tripadvisor_docs),
        },
        "er": er,
        "link_survival": link,
        "link_survival_in_calibration": calibration_link,
        "geocoding": geo,
        "geocoding_in_calibration": calibration_geo,
        "methodological_notes": [
            "In-sample ER metrics are optimistic because thresholds were calibrated on the "
            "same hand-labeled pool; cross-validation gives the generalization estimate.",
            "Geocoding distances are only observed for candidate pairs that survived the "
            "150 m spatial block; gross geocoding failures appear as missed matches, null "
            "coordinate coverage, or UNBLOCKABLE candidates rather than large distances.",
        ],
    }


def write_outputs(payload: dict[str, Any], settings: IntegrationAssessmentSettings) -> None:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = settings.output_dir / "integration_assessment_metrics.json"
    metrics_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )

    _write_csv(
        settings.output_dir / "integration_er_confusion.csv",
        payload["er"]["in_sample"]["confusion_rows"],
        CONFUSION_FIELDNAMES,
    )
    errors = [
        *payload["er"]["in_sample"]["errors"],
        *payload["link_survival"]["errors"],
    ]
    _write_csv(settings.output_dir / "integration_errors.csv", errors, ERROR_FIELDNAMES)
    _write_csv(
        settings.output_dir / "integration_geocoding_error.csv",
        payload["geocoding"]["rows"],
        GEOCODING_FIELDNAMES,
    )


def run_assessment(
    settings: IntegrationAssessmentSettings,
    *,
    gold_csvs: list[Path] | None = None,
    in_calibration_gold_csvs: list[Path] | None = None,
    collections: IntegrationCollections | None = None,
) -> dict[str, Any]:
    """Run the post-integration assessment and write JSON/CSV artifacts."""
    in_calibration_paths = settings.resolve_in_calibration_gold_paths(in_calibration_gold_csvs)
    in_calibration_gold_rows = load_gold_rows(in_calibration_paths)
    evaluation_paths = settings.resolve_gold_paths(gold_csvs)
    if evaluation_paths:
        gold_rows = load_gold_rows(evaluation_paths)
        calibration_ids = gold_ids(in_calibration_gold_rows)
        before_filter = len(gold_rows)
        gold_rows = [row for row in gold_rows if row["_id"] not in calibration_ids]
        excluded_overlap = before_filter - len(gold_rows)
    else:
        gold_rows = list(in_calibration_gold_rows)
        before_filter = len(gold_rows)
        excluded_overlap = 0
    collections = collections or open_collections(settings)
    payload = build_payload(
        settings=settings,
        gold_rows=gold_rows,
        in_calibration_gold_rows=in_calibration_gold_rows,
        evaluation_rows_after_csv_dedupe=before_filter,
        excluded_evaluation_overlap=excluded_overlap,
        candidates=_collection_docs(collections.candidates),
        links=_collection_docs(collections.links),
        integrated_docs=_collection_docs(collections.integrated),
        google_docs=_collection_docs(collections.google),
        tripadvisor_docs=_collection_docs(collections.tripadvisor),
    )
    write_outputs(payload, settings)
    return payload
