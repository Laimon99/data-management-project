from __future__ import annotations

import csv
import json
import logging
import random
from collections import Counter, defaultdict
from enum import Enum
from pathlib import Path
from typing import Any

import typer
from pymongo.errors import PyMongoError

from .config import ERSettings
from .scoring import MATCH, NON_MATCH, UNCERTAIN, label
from .transform import open_transform_collections

app = typer.Typer(add_completion=False, no_args_is_help=True)

SCORED_LABELS = (MATCH, NON_MATCH, UNCERTAIN)
CALIBRATION_COLUMNS = [
    "_id",
    "source",
    "google_id",
    "source_id",
    "is_chain",
    "chain_brand",
    "chain_hardening",
    "google_name",
    "source_name",
    "google_street",
    "source_street",
    "google_postal_code",
    "source_postal_code",
    "google_phone",
    "source_phone",
    "google_website",
    "source_website",
    "score",
    "dmin",
    "dmax",
    "label",
    "block_source",
    "fast_path",
    "name_sim",
    "geo_dist_m",
    "geo_score",
    "street_sim",
    "phone_match",
    "website_match",
    "postal_code_match",
    "cuisine_jaccard",
    "human_label",
]


class SourceOption(str, Enum):
    tripadvisor = "tripadvisor"
    thefork = "thefork"
    all = "all"


class ChainFilterOption(str, Enum):
    all = "all"
    chain = "chain"
    non_chain = "non_chain"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def select_calibration_sample(
    candidates: list[dict[str, Any]],
    *,
    sample_size: int,
    source: str = "all",
    chain_filter: str = "all",
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Select a deterministic stratified candidate sample for manual labeling."""
    if sample_size <= 0:
        return []

    filtered = [
        candidate
        for candidate in candidates
        if candidate.get("label") in SCORED_LABELS
        and candidate.get("score") is not None
        and (source == "all" or candidate.get("source") == source)
        and (
            chain_filter == "all"
            or (chain_filter == "chain" and candidate.get("is_chain") is True)
            or (chain_filter == "non_chain" and candidate.get("is_chain") is not True)
        )
    ]
    if len(filtered) <= sample_size:
        return filtered

    rng = random.Random(seed)
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in filtered:
        buckets[(str(candidate.get("source")), str(candidate.get("label")))].append(candidate)

    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    per_bucket = max(1, sample_size // len(buckets))
    for key in sorted(buckets):
        bucket = list(buckets[key])
        rng.shuffle(bucket)
        for candidate in bucket[:per_bucket]:
            selected.append(candidate)
            selected_ids.add(id(candidate))

    leftovers = [candidate for candidate in filtered if id(candidate) not in selected_ids]
    rng.shuffle(leftovers)
    selected.extend(leftovers[: max(sample_size - len(selected), 0)])
    return selected[:sample_size]


def _find_google(google_collection: Any, google_id: str | None) -> dict[str, Any] | None:
    if not google_id:
        return None
    return google_collection.find_one({"place_id": google_id}) or google_collection.find_one(
        {"_id": google_id}
    )


def _find_source(
    tripadvisor_collection: Any,
    thefork_collection: Any,
    source: str,
    source_id: str,
) -> dict[str, Any] | None:
    if source == "tripadvisor":
        return tripadvisor_collection.find_one(
            {"ta_location_id": source_id}
        ) or tripadvisor_collection.find_one({"_id": source_id})
    return thefork_collection.find_one({"tf_id": source_id}) or thefork_collection.find_one(
        {"_id": source_id}
    )


def _row_for_candidate(
    candidate: dict[str, Any],
    google_doc: dict[str, Any] | None,
    source_doc: dict[str, Any] | None,
) -> dict[str, str]:
    components = candidate.get("components") or {}
    row = {column: "" for column in CALIBRATION_COLUMNS}
    row.update(
        {
            "_id": _csv_value(candidate.get("_id")),
            "source": _csv_value(candidate.get("source")),
            "google_id": _csv_value(candidate.get("google_id")),
            "source_id": _csv_value(candidate.get("source_id")),
            "is_chain": _csv_value(candidate.get("is_chain")),
            "chain_brand": _csv_value(candidate.get("chain_brand")),
            "chain_hardening": _csv_value(candidate.get("chain_hardening")),
            "google_name": _csv_value((google_doc or {}).get("name")),
            "source_name": _csv_value((source_doc or {}).get("restaurant_name")),
            "google_street": _csv_value((google_doc or {}).get("street")),
            "source_street": _csv_value((source_doc or {}).get("street")),
            "google_postal_code": _csv_value((google_doc or {}).get("postal_code")),
            "source_postal_code": _csv_value((source_doc or {}).get("postal_code")),
            "google_phone": _csv_value((google_doc or {}).get("phone")),
            "source_phone": _csv_value((source_doc or {}).get("phone")),
            "google_website": _csv_value((google_doc or {}).get("website")),
            "source_website": _csv_value((source_doc or {}).get("website")),
            "score": _csv_value(candidate.get("score")),
            "dmin": _csv_value(candidate.get("dmin")),
            "dmax": _csv_value(candidate.get("dmax")),
            "label": _csv_value(candidate.get("label")),
            "block_source": _csv_value(candidate.get("block_source")),
            "fast_path": _csv_value(candidate.get("fast_path")),
        }
    )
    for component in (
        "name_sim",
        "geo_dist_m",
        "geo_score",
        "street_sim",
        "phone_match",
        "website_match",
        "postal_code_match",
        "cuisine_jaccard",
    ):
        row[component] = _csv_value(components.get(component))
    return row


def write_calibration_csv(
    google_collection: Any,
    tripadvisor_collection: Any,
    thefork_collection: Any,
    candidate_collection: Any,
    output: Path,
    *,
    sample_size: int = 120,
    source: str = "all",
    chain_filter: str = "all",
    seed: int = 42,
) -> int:
    query: dict[str, Any] = {"label": {"$in": list(SCORED_LABELS)}, "score": {"$ne": None}}
    if source != "all":
        query["source"] = source
    if chain_filter == "chain":
        query["is_chain"] = True
    elif chain_filter == "non_chain":
        query["is_chain"] = {"$ne": True}
    candidates = list(candidate_collection.find(query))
    sample = select_calibration_sample(
        candidates,
        sample_size=sample_size,
        source=source,
        chain_filter=chain_filter,
        seed=seed,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CALIBRATION_COLUMNS)
        writer.writeheader()
        for candidate in sample:
            google_doc = _find_google(google_collection, candidate.get("google_id"))
            source_doc = _find_source(
                tripadvisor_collection,
                thefork_collection,
                str(candidate.get("source")),
                str(candidate.get("source_id")),
            )
            writer.writerow(_row_for_candidate(candidate, google_doc, source_doc))
    return len(sample)


def _bool_value(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def _parse_labeled_rows(rows: list[dict[str, str]]) -> list[tuple[float, str, str, bool]]:
    parsed: list[tuple[float, str, str, bool]] = []
    for row in rows:
        human_label = (row.get("human_label") or "").strip().upper()
        if human_label not in {MATCH, NON_MATCH}:
            continue
        try:
            score = float(row.get("score") or "")
        except ValueError:
            continue
        source = (row.get("source") or "unknown").strip().lower()
        parsed.append((score, human_label, source, _bool_value(row.get("is_chain"))))
    return parsed


def _score_summary(scores: list[float]) -> dict[str, float | None]:
    if not scores:
        return {"min": None, "p25": None, "p50": None, "p75": None, "max": None}
    ordered = sorted(scores)

    def quantile(q: float) -> float:
        index = round((len(ordered) - 1) * q)
        return ordered[index]

    return {
        "min": ordered[0],
        "p25": quantile(0.25),
        "p50": quantile(0.50),
        "p75": quantile(0.75),
        "max": ordered[-1],
    }


def _metrics_for_thresholds(
    labeled: list[tuple[float, str, str, bool]],
    *,
    dmin: float,
    dmax: float,
) -> dict[str, Any]:
    predicted = [
        (label(score, dmin, dmax), human_label)
        for score, human_label, _source, _is_chain in labeled
    ]
    human_match = sum(1 for _, human_label in predicted if human_label == MATCH)
    predicted_match = sum(1 for predicted_label, _ in predicted if predicted_label == MATCH)
    true_predicted_match = sum(
        1
        for predicted_label, human_label in predicted
        if predicted_label == MATCH and human_label == MATCH
    )
    match_precision = true_predicted_match / predicted_match if predicted_match > 0 else None
    true_match_kept = sum(
        1
        for predicted_label, human_label in predicted
        if human_label == MATCH and predicted_label in {MATCH, UNCERTAIN}
    )
    match_recall_kept = true_match_kept / human_match if human_match > 0 else None
    uncertain = sum(1 for predicted_label, _ in predicted if predicted_label == UNCERTAIN)
    non_match_false_negatives = sum(
        1
        for predicted_label, human_label in predicted
        if predicted_label == NON_MATCH and human_label == MATCH
    )

    return {
        "dmin": dmin,
        "dmax": dmax,
        "match_precision": match_precision,
        "true_match_recall_into_match_or_uncertain": match_recall_kept,
        "uncertain_rate": uncertain / len(labeled) if labeled else None,
        "predicted_match": predicted_match,
        "predicted_uncertain": uncertain,
        "false_non_match_for_true_match": non_match_false_negatives,
        "meets_targets": (
            match_precision is not None
            and match_precision >= 0.90
            and match_recall_kept is not None
            and match_recall_kept >= 0.97
        ),
    }


def _suggest_thresholds(labeled: list[tuple[float, str, str, bool]]) -> dict[str, Any]:
    scores = [score for score, _human_label, _source, _is_chain in labeled]
    human_counts = Counter(human_label for _score, human_label, _source, _is_chain in labeled)
    if not labeled:
        return {
            "labeled_rows": 0,
            "human_counts": {},
            "score_summary": _score_summary(scores),
            "suggestions_meet_targets": False,
            "suggestions": [],
        }

    thresholds = sorted({0.0, 0.40, 0.85, 1.0, *scores})
    all_metrics = [
        _metrics_for_thresholds(labeled, dmin=dmin, dmax=dmax)
        for dmin in thresholds
        for dmax in thresholds
        if dmin < dmax
    ]
    meeting = [metrics for metrics in all_metrics if metrics["meets_targets"]]
    pool = meeting or all_metrics

    def rank(metrics: dict[str, Any]) -> tuple[float, float, float]:
        precision = metrics["match_precision"] or 0.0
        recall = metrics["true_match_recall_into_match_or_uncertain"] or 0.0
        uncertain_rate = metrics["uncertain_rate"] if metrics["uncertain_rate"] is not None else 1.0
        return uncertain_rate, -precision, -recall

    suggestions = sorted(pool, key=rank)[:5]
    return {
        "labeled_rows": len(labeled),
        "human_counts": dict(human_counts),
        "score_summary": _score_summary(scores),
        "suggestions_meet_targets": bool(meeting),
        "suggestions": suggestions,
    }


def _operational_recommendation(
    labeled: list[tuple[float, str, str, bool]],
) -> dict[str, Any] | None:
    if not labeled:
        return None

    thresholds = [index / 100 for index in range(101)]
    all_metrics = [
        _metrics_for_thresholds(labeled, dmin=dmin, dmax=dmax)
        for dmin in thresholds
        for dmax in thresholds
        if dmin < dmax
    ]
    meeting = [metrics for metrics in all_metrics if metrics["meets_targets"]]
    bounded_uncertain = [
        metrics
        for metrics in meeting
        if metrics["uncertain_rate"] is not None and metrics["uncertain_rate"] <= 0.10
    ]
    pool = bounded_uncertain or meeting or all_metrics

    def rank(metrics: dict[str, Any]) -> tuple[int, float, float, float]:
        precision = metrics["match_precision"] or 0.0
        recall = metrics["true_match_recall_into_match_or_uncertain"] or 0.0
        uncertain_rate = metrics["uncertain_rate"] if metrics["uncertain_rate"] is not None else 1.0
        false_non_match = int(metrics["false_non_match_for_true_match"])
        return false_non_match, -precision, uncertain_rate, -recall

    selected = sorted(pool, key=rank)[0]
    return {
        "dmin": selected["dmin"],
        "dmax": selected["dmax"],
        "match_precision": selected["match_precision"],
        "true_match_recall_into_match_or_uncertain": selected[
            "true_match_recall_into_match_or_uncertain"
        ],
        "uncertain_rate": selected["uncertain_rate"],
        "false_non_match_for_true_match": selected["false_non_match_for_true_match"],
        "based_on_labeled_rows": len(labeled),
    }


def _cli_float(value: float) -> str:
    text = f"{value:.2f}"
    return text.rstrip("0").rstrip(".")


def _recommended_source_thresholds(
    labeled: list[tuple[float, str, str, bool]],
    *,
    chain_flags: bool = False,
) -> dict[str, Any]:
    by_source: dict[str, list[tuple[float, str, str, bool]]] = defaultdict(list)
    for row in labeled:
        by_source[row[2]].append(row)

    recommendations: dict[str, Any] = {}
    command = ["uv run dataman-entity-resolve"]
    for source in ("tripadvisor", "thefork"):
        selected = _operational_recommendation(by_source.get(source, []))
        if selected is None:
            continue
        recommendations[source] = selected
        dmin_flag = f"--dmin-{source}"
        dmax_flag = f"--dmax-{source}"
        if chain_flags:
            dmin_flag = f"--dmin-chain-{source}"
            dmax_flag = f"--dmax-chain-{source}"
        command.extend(
            [
                dmin_flag,
                _cli_float(float(selected["dmin"])),
                dmax_flag,
                _cli_float(float(selected["dmax"])),
            ]
        )

    if recommendations:
        recommendations["example_command"] = " ".join(command)
        recommendations["note"] = (
            "Use these as source-specific overrides. If a source-specific flag is "
            "omitted, the resolver falls back to the global --dmin/--dmax values."
        )
    return recommendations


def analyze_calibration_rows(rows: list[dict[str, str]]) -> dict[str, Any]:
    labeled = _parse_labeled_rows(rows)
    report = _suggest_thresholds(labeled)
    by_source: dict[str, list[tuple[float, str, str, bool]]] = defaultdict(list)
    by_chain: dict[str, list[tuple[float, str, str, bool]]] = {
        "chain": [],
        "non_chain": [],
    }
    by_chain_source: dict[str, dict[str, list[tuple[float, str, str, bool]]]] = {
        "chain": defaultdict(list),
        "non_chain": defaultdict(list),
    }
    for row in labeled:
        by_source[row[2]].append(row)
        chain_key = "chain" if row[3] else "non_chain"
        by_chain[chain_key].append(row)
        by_chain_source[chain_key][row[2]].append(row)
    report["source_suggestions"] = {
        source: _suggest_thresholds(source_labeled)
        for source, source_labeled in sorted(by_source.items())
        if source in {"tripadvisor", "thefork"}
    }
    report["recommended_source_thresholds"] = _recommended_source_thresholds(labeled)
    report["chain_suggestions"] = {
        key: _suggest_thresholds(value) for key, value in by_chain.items() if value
    }
    report["chain_source_suggestions"] = {
        chain_key: {
            source: _suggest_thresholds(source_labeled)
            for source, source_labeled in sorted(source_map.items())
            if source in {"tripadvisor", "thefork"}
        }
        for chain_key, source_map in by_chain_source.items()
        if any(source_map.values())
    }
    report["recommended_chain_source_thresholds"] = _recommended_source_thresholds(
        by_chain["chain"],
        chain_flags=True,
    )
    return report


@app.command("export")
def export_sample(
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="CSV path for the manual calibration sample.",
    ),
    sample_size: int = typer.Option(
        120,
        "--sample-size",
        min=1,
        help="Number of scored candidate rows to export.",
    ),
    source: SourceOption = typer.Option(
        SourceOption.all,
        "--source",
        case_sensitive=False,
        help="Candidate source to sample: tripadvisor, thefork, or all.",
    ),
    chain_filter: ChainFilterOption = typer.Option(
        ChainFilterOption.all,
        "--chain-filter",
        case_sensitive=False,
        help="Candidate chain filter: all, chain, or non_chain.",
    ),
    seed: int = typer.Option(
        42,
        "--seed",
        help="Deterministic random seed for stratified sampling.",
    ),
) -> None:
    """Export a labelable ER calibration sample CSV."""
    _configure_logging()

    settings = ERSettings()
    client = None
    try:
        client, google, tripadvisor, thefork, candidates = open_transform_collections(settings)
        written = write_calibration_csv(
            google,
            tripadvisor,
            thefork,
            candidates,
            output,
            sample_size=sample_size,
            source=source.value,
            chain_filter=chain_filter.value,
            seed=seed,
        )
    except PyMongoError as exc:
        typer.echo(f"MongoDB error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        if client is not None:
            client.close()

    typer.echo(json.dumps({"output": str(output), "written": written}, indent=2))


@app.command("analyze")
def analyze(
    csv_path: Path = typer.Argument(
        ...,
        help="Calibration CSV with human_label values filled in.",
    ),
) -> None:
    """Analyze a manually labeled calibration CSV and suggest thresholds."""
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    typer.echo(json.dumps(analyze_calibration_rows(rows), indent=2))
