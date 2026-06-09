from __future__ import annotations

from typing import Any

from transform.entity_resolution.scoring import MATCH

from .er_metrics import effective_candidate_label

SURVIVAL_FIELDNAMES = [
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


def _index_by_id(docs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(doc.get("_id")): doc for doc in docs if doc.get("_id")}


def _link_key(source: str, google_id: str, source_id: str) -> str:
    return f"{source}:{google_id}:{source_id}"


def _links_by_pair(links: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for link in links:
        source = str(link.get("source") or "")
        google_id = str(link.get("google_id") or "")
        source_id = str(link.get("source_id") or "")
        if source and google_id and source_id:
            lookup[(source, google_id, source_id)] = link
        link_id = str(link.get("_id") or "")
        if link_id.count(":") >= 2:
            parts = link_id.split(":", 2)
            lookup.setdefault((parts[0], parts[1], parts[2]), link)
    return lookup


def _source_id_values(source_block: dict[str, Any] | None) -> set[str]:
    if not source_block:
        return set()
    ids = source_block.get("ids") or {}
    return {str(value) for value in ids.values() if value not in (None, "")}


def _is_integrated(
    integrated_doc: dict[str, Any] | None,
    *,
    source: str,
    source_id: str,
) -> bool:
    if integrated_doc is None:
        return False
    sources = integrated_doc.get("sources") or {}
    return source_id in _source_id_values(sources.get(source))


def compute_link_metrics(
    gold_rows: list[dict[str, str]],
    candidates: list[dict[str, Any]],
    links: list[dict[str, Any]],
    integrated_docs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measure true-match survival through 1:1 link selection and integration."""
    candidates_by_id = _index_by_id(candidates)
    links_by_pair = _links_by_pair(links)
    integrated_by_id = _index_by_id(integrated_docs)

    total_true_matches = 0
    linked = 0
    integrated = 0
    classifier_match = 0
    dropped_by_selection = 0
    missing_source_doc = 0
    errors: list[dict[str, Any]] = []

    for row in gold_rows:
        if str(row.get("human_label", "")).upper() != MATCH:
            continue
        total_true_matches += 1
        source = str(row.get("source") or "").strip().lower()
        google_id = str(row.get("google_id") or "").strip()
        source_id = str(row.get("source_id") or "").strip()
        candidate = candidates_by_id.get(row["_id"])
        predicted = effective_candidate_label(candidate)
        if predicted == MATCH:
            classifier_match += 1

        link = links_by_pair.get((source, google_id, source_id)) or _index_by_id(links).get(
            _link_key(source, google_id, source_id)
        )
        is_linked = link is not None and str(link.get("effective_label")) == MATCH
        if is_linked:
            linked += 1

        integrated_doc = integrated_by_id.get(f"google:{google_id}")
        is_survived = _is_integrated(integrated_doc, source=source, source_id=source_id)
        if is_survived:
            integrated += 1

        if predicted == MATCH and not is_linked:
            dropped_by_selection += 1
            errors.append(
                {
                    "issue_type": "dropped_by_1to1_selection",
                    "candidate_id": row["_id"],
                    "source": source,
                    "google_id": google_id,
                    "source_id": source_id,
                    "human_label": MATCH,
                    "predicted_label": predicted,
                    "score": (candidate or {}).get("score", row.get("score", "")),
                    "detail": "Human MATCH classified as MATCH but absent from selected links.",
                }
            )
        elif not is_linked:
            errors.append(
                {
                    "issue_type": "true_match_not_linked",
                    "candidate_id": row["_id"],
                    "source": source,
                    "google_id": google_id,
                    "source_id": source_id,
                    "human_label": MATCH,
                    "predicted_label": predicted or "",
                    "score": (candidate or {}).get("score", row.get("score", "")),
                    "detail": "Human MATCH did not survive to entity_resolution_links.",
                }
            )

        if is_linked and not is_survived:
            missing_source_doc += 1
            errors.append(
                {
                    "issue_type": "linked_missing_from_integrated",
                    "candidate_id": row["_id"],
                    "source": source,
                    "google_id": google_id,
                    "source_id": source_id,
                    "human_label": MATCH,
                    "predicted_label": predicted or "",
                    "score": (candidate or {}).get("score", row.get("score", "")),
                    "detail": "Selected link is not represented in restaurants_integrated.",
                }
            )

    return {
        "total_true_matches": total_true_matches,
        "classifier_match_true_matches": classifier_match,
        "linked_true_matches": linked,
        "integrated_true_matches": integrated,
        "link_survival_rate": linked / total_true_matches if total_true_matches else None,
        "integration_survival_rate": (
            integrated / total_true_matches if total_true_matches else None
        ),
        "dropped_by_1to1_selection": dropped_by_selection,
        "missing_source_doc_count": missing_source_doc,
        "errors": errors,
    }
