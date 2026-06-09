from __future__ import annotations

import random
from collections import Counter, defaultdict
from statistics import mean, pstdev
from typing import Any

from transform.entity_resolution.calibrate import (
    _metrics_for_thresholds,
    _operational_recommendation,
    _parse_labeled_rows,
)
from transform.entity_resolution.scoring import MATCH, NON_MATCH, UNCERTAIN, label

PREDICTED_LABELS = (MATCH, UNCERTAIN, NON_MATCH)
ERROR_FIELDNAMES = [
    "issue_type",
    "candidate_id",
    "source",
    "google_id",
    "source_id",
    "human_label",
    "predicted_label",
    "score",
    "detail",
]
CONFUSION_FIELDNAMES = [
    "group_type",
    "group",
    "human_label",
    "predicted_match",
    "predicted_uncertain",
    "predicted_non_match",
    "total",
    "match_precision",
    "match_recall_strict",
    "match_recall_kept",
    "match_f1_strict",
    "accuracy",
    "uncertain_rate",
    "missing_from_mongo",
]


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def effective_candidate_label(candidate: dict[str, Any] | None) -> str | None:
    if candidate is None:
        return None
    llm_label = candidate.get("llm_label")
    if not is_blank(llm_label):
        return str(llm_label).strip().upper()
    candidate_label = candidate.get("label")
    if not is_blank(candidate_label):
        return str(candidate_label).strip().upper()
    score = as_float(candidate.get("score"))
    dmin = as_float(candidate.get("dmin"))
    dmax = as_float(candidate.get("dmax"))
    if score is not None and dmin is not None and dmax is not None:
        return label(score, dmin=dmin, dmax=dmax)
    return None


def _candidate_index(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(candidate.get("_id")): candidate for candidate in candidates if candidate.get("_id")
    }


def _source_for(row: dict[str, str], candidate: dict[str, Any] | None) -> str:
    return str((candidate or {}).get("source") or row.get("source") or "unknown").strip().lower()


def _chain_for(row: dict[str, str], candidate: dict[str, Any] | None) -> bool:
    value = (candidate or {}).get("is_chain")
    if value is None:
        value = row.get("is_chain")
    return bool(value) if isinstance(value, bool) else as_bool(value)


def _predicted_label(candidate: dict[str, Any] | None) -> str | None:
    predicted = effective_candidate_label(candidate)
    if predicted in PREDICTED_LABELS:
        return predicted
    return None


def _empty_confusion() -> dict[str, Any]:
    return {
        "matrix": {human: {pred: 0 for pred in PREDICTED_LABELS} for human in (MATCH, NON_MATCH)},
        "total": 0,
        "missing_from_mongo": 0,
    }


def _add_confusion(groups: dict[tuple[str, str], dict[str, Any]], key: tuple[str, str]) -> None:
    if key not in groups:
        groups[key] = _empty_confusion()


def _summarize_confusion(confusion: dict[str, Any]) -> dict[str, Any]:
    matrix = confusion["matrix"]
    tp = matrix[MATCH][MATCH]
    predicted_match = matrix[MATCH][MATCH] + matrix[NON_MATCH][MATCH]
    human_match = sum(matrix[MATCH].values())
    true_kept = matrix[MATCH][MATCH] + matrix[MATCH][UNCERTAIN]
    true_negative = matrix[NON_MATCH][NON_MATCH]
    total = confusion["total"]

    precision = tp / predicted_match if predicted_match else None
    recall = tp / human_match if human_match else None
    kept_recall = true_kept / human_match if human_match else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall) > 0
        else None
    )
    uncertain = matrix[MATCH][UNCERTAIN] + matrix[NON_MATCH][UNCERTAIN]
    return {
        "total": total,
        "missing_from_mongo": confusion["missing_from_mongo"],
        "match_precision": precision,
        "match_recall_strict": recall,
        "match_recall_kept": kept_recall,
        "match_f1_strict": f1,
        "accuracy": (tp + true_negative) / total if total else None,
        "uncertain_rate": uncertain / total if total else None,
    }


def _confusion_rows(
    groups: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}
    for (group_type, group), confusion in sorted(groups.items()):
        summary = _summarize_confusion(confusion)
        summaries[f"{group_type}:{group}"] = {
            "group_type": group_type,
            "group": group,
            "matrix": confusion["matrix"],
            **summary,
        }
        for human_label in (MATCH, NON_MATCH):
            matrix_row = confusion["matrix"][human_label]
            rows.append(
                {
                    "group_type": group_type,
                    "group": group,
                    "human_label": human_label,
                    "predicted_match": matrix_row[MATCH],
                    "predicted_uncertain": matrix_row[UNCERTAIN],
                    "predicted_non_match": matrix_row[NON_MATCH],
                    "total": sum(matrix_row.values()),
                    **summary,
                }
            )
    return rows, summaries


def compute_er_metrics(
    gold_rows: list[dict[str, str]],
    candidates: list[dict[str, Any]],
    *,
    cv_gold_rows: list[dict[str, str]] | None = None,
    cv_folds: int = 5,
    cv_seed: int = 42,
) -> dict[str, Any]:
    """Compute in-sample Mongo-vs-gold and cross-validated ER metrics."""
    candidates_by_id = _candidate_index(candidates)
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []

    for key in (("overall", "all"),):
        _add_confusion(groups, key)

    for row in gold_rows:
        candidate_id = row["_id"]
        candidate = candidates_by_id.get(candidate_id)
        human_label = str(row.get("human_label", "")).upper()
        source = _source_for(row, candidate)
        chain_key = "chain" if _chain_for(row, candidate) else "non_chain"
        for key in (("overall", "all"), ("source", source), ("chain", chain_key)):
            _add_confusion(groups, key)

        predicted = _predicted_label(candidate)
        if candidate is None or predicted is None:
            for key in (("overall", "all"), ("source", source), ("chain", chain_key)):
                groups[key]["missing_from_mongo"] += 1
            errors.append(
                {
                    "issue_type": "missing_candidate" if candidate is None else "missing_label",
                    "candidate_id": candidate_id,
                    "source": source,
                    "google_id": row.get("google_id", ""),
                    "source_id": row.get("source_id", ""),
                    "human_label": human_label,
                    "predicted_label": "",
                    "score": row.get("score", ""),
                    "detail": "Gold row has no usable candidate label in Mongo.",
                }
            )
            continue

        for key in (("overall", "all"), ("source", source), ("chain", chain_key)):
            groups[key]["matrix"][human_label][predicted] += 1
            groups[key]["total"] += 1

        is_correct = (human_label == MATCH and predicted == MATCH) or (
            human_label == NON_MATCH and predicted == NON_MATCH
        )
        if not is_correct:
            errors.append(
                {
                    "issue_type": "er_misclassification",
                    "candidate_id": candidate_id,
                    "source": source,
                    "google_id": row.get("google_id", candidate.get("google_id", "")),
                    "source_id": row.get("source_id", candidate.get("source_id", "")),
                    "human_label": human_label,
                    "predicted_label": predicted,
                    "score": candidate.get("score", row.get("score", "")),
                    "detail": "Predicted label disagrees with strict human label.",
                }
            )

    confusion_rows, summaries = _confusion_rows(groups)
    return {
        "gold_rows": len(gold_rows),
        "in_sample": {
            "summaries": summaries,
            "confusion_rows": confusion_rows,
            "errors": errors,
        },
        "cross_validation": cross_validate_thresholds(
            cv_gold_rows if cv_gold_rows is not None else gold_rows,
            folds=cv_folds,
            seed=cv_seed,
        ),
        "cross_validation_gold_rows": len(cv_gold_rows if cv_gold_rows is not None else gold_rows),
    }


def _folds(items: list[Any], *, folds: int, seed: int) -> list[list[Any]]:
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)
    fold_count = min(max(folds, 2), len(shuffled))
    return [shuffled[index::fold_count] for index in range(fold_count)]


def _mean_std(values: list[float | None]) -> dict[str, float | None]:
    finite = [value for value in values if value is not None]
    if not finite:
        return {"mean": None, "std": None}
    return {"mean": mean(finite), "std": pstdev(finite) if len(finite) > 1 else 0.0}


def _cv_for_rows(
    labeled: list[tuple[float, str, str, bool]],
    *,
    folds: int,
    seed: int,
) -> dict[str, Any]:
    if len(labeled) < 2:
        return {"folds": [], "summary": {}}

    fold_metrics: list[dict[str, Any]] = []
    split = _folds(labeled, folds=folds, seed=seed)
    for fold_index, test in enumerate(split, 1):
        train = [row for fold in split if fold is not test for row in fold]
        selected = _operational_recommendation(train)
        if selected is None:
            continue
        metrics = _metrics_for_thresholds(
            test,
            dmin=float(selected["dmin"]),
            dmax=float(selected["dmax"]),
        )
        fold_metrics.append(
            {
                "fold": fold_index,
                "train_rows": len(train),
                "test_rows": len(test),
                "dmin": selected["dmin"],
                "dmax": selected["dmax"],
                **metrics,
            }
        )

    return {
        "folds": fold_metrics,
        "summary": {
            "match_precision": _mean_std([row["match_precision"] for row in fold_metrics]),
            "match_recall_kept": _mean_std(
                [row["true_match_recall_into_match_or_uncertain"] for row in fold_metrics]
            ),
            "uncertain_rate": _mean_std([row["uncertain_rate"] for row in fold_metrics]),
        },
    }


def cross_validate_thresholds(
    gold_rows: list[dict[str, str]],
    *,
    folds: int = 5,
    seed: int = 42,
) -> dict[str, Any]:
    labeled = _parse_labeled_rows(gold_rows)
    by_source: dict[str, list[tuple[float, str, str, bool]]] = defaultdict(list)
    for row in labeled:
        by_source[row[2]].append(row)

    return {
        "overall": _cv_for_rows(labeled, folds=folds, seed=seed),
        "by_source": {
            source: _cv_for_rows(rows, folds=folds, seed=seed)
            for source, rows in sorted(by_source.items())
        },
        "human_counts": dict(Counter(row[1] for row in labeled)),
    }
