"""Mongo orchestration for LLM adjudication of uncertain ER candidates."""

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pymongo.errors import PyMongoError

from transform.entity_resolution.scoring import UNCERTAIN

from .client import LlmClient
from .config import LlmERSettings
from .models import CandidateVenue, Decision, GroupResult, MatchGroup, SourceVenue
from .policy import apply_policy, input_hash
from .prompt import build_messages, top_candidates

SOURCE_ALL = "all"
SOURCE_TRIPADVISOR = "tripadvisor"
SOURCE_THEFORK = "thefork"
Mode = Literal["dry-run", "mock", "openai"]

GOOGLE_PROJECTION = {
    "_id": 1,
    "place_id": 1,
    "name": 1,
    "address": 1,
    "street": 1,
    "house_number": 1,
    "postal_code": 1,
    "latitude": 1,
    "longitude": 1,
    "phone": 1,
    "website": 1,
    "rating": 1,
    "review_count": 1,
    "cuisines": 1,
}

SOURCE_PROJECTION = {
    "_id": 1,
    "ta_location_id": 1,
    "tf_id": 1,
    "restaurant_name": 1,
    "address": 1,
    "street": 1,
    "house_number": 1,
    "postal_code": 1,
    "latitude": 1,
    "longitude": 1,
    "phone": 1,
    "website": 1,
    "rating": 1,
    "total_review": 1,
    "review_count": 1,
    "cuisines": 1,
}


@dataclass
class LlmERReport:
    mode: str
    apply: bool
    force: bool
    source: str
    read_candidates: int = 0
    groups: int = 0
    prompt_candidates: int = 0
    llm_calls: int = 0
    missing_google: int = 0
    missing_source: int = 0
    skipped_empty_groups: int = 0
    concurrency: int = 1
    decision_counts: dict[str, int] = field(default_factory=dict)
    final_decision_counts: dict[str, int] = field(default_factory=dict)
    candidate_update_counts: dict[str, int] = field(default_factory=dict)
    mongo_modified: int = 0
    mongo_skipped_existing: int = 0
    output_jsonl: str | None = None


@dataclass
class _ProcessedGroup:
    index: int
    result: GroupResult
    update_counts: Counter[str] = field(default_factory=Counter)
    mongo_modified: int = 0
    mongo_skipped: int = 0


def _selected_sources(source: str) -> tuple[str, ...]:
    if source == SOURCE_ALL:
        return SOURCE_TRIPADVISOR, SOURCE_THEFORK
    if source in {SOURCE_TRIPADVISOR, SOURCE_THEFORK}:
        return (source,)
    raise ValueError("source must be one of: tripadvisor, thefork, all")


def _candidate_query(source: str, *, force: bool) -> dict[str, Any]:
    query: dict[str, Any] = {"label": UNCERTAIN}
    if source != SOURCE_ALL:
        query["source"] = source
    return query


def _google_doc(collection: Any, google_id: str | None) -> dict[str, Any] | None:
    if not google_id:
        return None
    return collection.find_one({"place_id": google_id}, GOOGLE_PROJECTION) or collection.find_one(
        {"_id": google_id}, GOOGLE_PROJECTION
    )


def _source_doc(
    tripadvisor_collection: Any,
    thefork_collection: Any,
    source: str,
    source_id: str | None,
) -> dict[str, Any] | None:
    if not source_id:
        return None
    if source == SOURCE_TRIPADVISOR:
        return tripadvisor_collection.find_one(
            {"ta_location_id": source_id}, SOURCE_PROJECTION
        ) or tripadvisor_collection.find_one({"_id": source_id}, SOURCE_PROJECTION)
    return thefork_collection.find_one(
        {"tf_id": source_id}, SOURCE_PROJECTION
    ) or thefork_collection.find_one({"_id": source_id}, SOURCE_PROJECTION)


def _cuisines(doc: dict[str, Any]) -> list[str]:
    value = doc.get("cuisines")
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _review_count(doc: dict[str, Any], source: str) -> int | None:
    value = doc.get("total_review") if source == SOURCE_TRIPADVISOR else doc.get("review_count")
    return int(value) if value is not None else None


def _source_venue(source_doc: dict[str, Any], source: str, source_id: str) -> SourceVenue:
    return SourceVenue(
        source=source,  # type: ignore[arg-type]
        source_id=source_id,
        name=source_doc.get("restaurant_name") or source_doc.get("name"),
        address=source_doc.get("address"),
        street=source_doc.get("street"),
        house_number=source_doc.get("house_number"),
        postal_code=source_doc.get("postal_code"),
        latitude=source_doc.get("latitude"),
        longitude=source_doc.get("longitude"),
        phone=source_doc.get("phone"),
        website=source_doc.get("website"),
        rating=source_doc.get("rating"),
        review_count=_review_count(source_doc, source),
        cuisines=_cuisines(source_doc),
    )


def _candidate_venue(candidate_doc: dict[str, Any], google_doc: dict[str, Any]) -> CandidateVenue:
    return CandidateVenue(
        candidate_id=str(candidate_doc["_id"]),
        google_id=str(candidate_doc["google_id"]),
        name=google_doc.get("name"),
        address=google_doc.get("address"),
        street=google_doc.get("street"),
        house_number=google_doc.get("house_number"),
        postal_code=google_doc.get("postal_code"),
        latitude=google_doc.get("latitude"),
        longitude=google_doc.get("longitude"),
        phone=google_doc.get("phone"),
        website=google_doc.get("website"),
        rating=google_doc.get("rating"),
        review_count=google_doc.get("review_count"),
        cuisines=_cuisines(google_doc),
        score=candidate_doc.get("score"),
        dmin=candidate_doc.get("dmin"),
        dmax=candidate_doc.get("dmax"),
        block_source=candidate_doc.get("block_source"),
        fast_path=candidate_doc.get("fast_path"),
        is_chain=candidate_doc.get("is_chain") is True,
        chain_brand=candidate_doc.get("chain_brand"),
        chain_hardening=list(candidate_doc.get("chain_hardening") or []),
        components=dict(candidate_doc.get("components") or {}),
    )


def load_groups(
    google_collection: Any,
    tripadvisor_collection: Any,
    thefork_collection: Any,
    candidate_collection: Any,
    settings: LlmERSettings,
    *,
    source: str = SOURCE_ALL,
    force: bool = False,
    limit: int | None = None,
    report: LlmERReport | None = None,
) -> list[MatchGroup]:
    """Load candidate groups from Mongo in the internal prompt format."""
    _selected_sources(source)
    cursor = candidate_collection.find(_candidate_query(source, force=force)).sort(
        [("source", 1), ("source_id", 1), ("score", -1)]
    )
    raw_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    read_candidates = 0
    for doc in cursor:
        read_candidates += 1
        raw_groups[(str(doc.get("source")), str(doc.get("source_id")))].append(doc)
    if report is not None:
        report.read_candidates = read_candidates

    groups: list[MatchGroup] = []
    for (group_source, source_id), candidate_docs in raw_groups.items():
        if not force and any(
            doc.get("llm_label") is not None or "llm_updated_at" in doc
            for doc in candidate_docs
        ):
            continue

        source_doc = _source_doc(
            tripadvisor_collection,
            thefork_collection,
            group_source,
            source_id,
        )
        if source_doc is None:
            if report is not None:
                report.missing_source += len(candidate_docs)
            continue

        candidates: list[CandidateVenue] = []
        for candidate_doc in candidate_docs:
            google_doc = _google_doc(google_collection, candidate_doc.get("google_id"))
            if google_doc is None:
                if report is not None:
                    report.missing_google += 1
                continue
            candidates.append(_candidate_venue(candidate_doc, google_doc))

        if not candidates:
            if report is not None:
                report.skipped_empty_groups += 1
            continue

        prompt_candidates = top_candidates(candidates, settings.max_candidates)
        groups.append(
            MatchGroup(
                group_id=f"{group_source}:{source_id}",
                source_venue=_source_venue(source_doc, group_source, source_id),
                candidates=prompt_candidates,
                total_candidate_count=len(candidates),
                all_candidate_ids=[str(doc["_id"]) for doc in candidate_docs],
            )
        )
        if limit is not None and len(groups) >= limit:
            break

    if report is not None:
        report.groups = len(groups)
        report.prompt_candidates = sum(len(group.candidates) for group in groups)
    return groups


def dry_run_records(groups: list[MatchGroup], settings: LlmERSettings) -> list[dict[str, Any]]:
    return [
        {
            "group_id": group.group_id,
            "input_hash": input_hash(group),
            "model": settings.llm_match_model,
            "prompt_version": settings.prompt_version,
            "prompt_candidate_count": len(group.candidates),
            "total_candidate_count": group.total_candidate_count,
            "messages": build_messages(group),
        }
        for group in groups
    ]


def _update_payload(result: GroupResult, label: Decision | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "llm_status": "RESOLVED" if label is not None else "UNCERTAIN",
        "llm_decision": result.llm_decision.value,
        "llm_final_decision": result.final_decision.value,
        "llm_selected_candidate_id": result.matched_candidate_id,
        "llm_model": result.llm_model,
        "llm_confidence": result.confidence,
        "llm_reason": result.reason,
        "llm_risk_flags": [flag.value for flag in result.risk_flags],
        "llm_validation_notes": result.validation_notes,
        "llm_prompt_version": result.prompt_version,
        "llm_input_hash": result.input_hash,
        "llm_prompt_candidate_count": result.prompt_candidate_count,
        "llm_total_candidate_count": result.total_candidate_count,
        "llm_updated_at": datetime.now(UTC),
    }
    if label is not None:
        payload["llm_label"] = label.value
    return payload


def apply_result(
    candidate_collection: Any,
    result: GroupResult,
    *,
    force: bool = False,
) -> tuple[int, int]:
    """Apply one group result. Returns (modified, skipped_existing)."""
    modified = skipped = 0
    if result.candidate_updates:
        for candidate_id, label in result.candidate_updates.items():
            query: dict[str, Any] = {"_id": candidate_id}
            if not force:
                query["llm_label"] = None
            update = {"$set": _update_payload(result, label)}
            update_result = candidate_collection.update_one(query, update)
            if update_result.matched_count == 0 and not force:
                skipped += 1
            modified += int(update_result.modified_count)
        return modified, skipped

    return 0, 0


def apply_uncertain_metadata(
    candidate_collection: Any,
    result: GroupResult,
    candidate_ids: list[str],
    *,
    force: bool = False,
) -> tuple[int, int]:
    if not candidate_ids:
        return 0, 0
    query: dict[str, Any] = {"_id": {"$in": candidate_ids}}
    if not force:
        query["llm_label"] = None
    update_result = candidate_collection.update_many(query, {"$set": _update_payload(result, None)})
    skipped = 0 if force else max(len(candidate_ids) - int(update_result.matched_count), 0)
    return int(update_result.modified_count), skipped


def _process_group(
    index: int,
    group: MatchGroup,
    client: LlmClient,
    settings: LlmERSettings,
    *,
    apply: bool,
    force: bool,
    candidate_collection: Any | None,
) -> _ProcessedGroup:
    decision = client.decide(group)
    result = apply_policy(group, decision, settings, model=client.model)
    update_counts: Counter[str] = Counter()
    mongo_modified = mongo_skipped = 0

    if apply:
        if candidate_collection is None:
            raise ValueError("candidate_collection is required when apply=True.")
        if result.candidate_updates:
            mongo_modified, mongo_skipped = apply_result(
                candidate_collection,
                result,
                force=force,
            )
            for label in result.candidate_updates.values():
                update_counts[label.value] += 1
        else:
            candidate_ids = group.all_candidate_ids or [
                candidate.candidate_id for candidate in group.candidates
            ]
            mongo_modified, mongo_skipped = apply_uncertain_metadata(
                candidate_collection,
                result,
                candidate_ids,
                force=force,
            )
            update_counts["UNCERTAIN_METADATA_ONLY"] += len(candidate_ids)

    return _ProcessedGroup(
        index=index,
        result=result,
        update_counts=update_counts,
        mongo_modified=mongo_modified,
        mongo_skipped=mongo_skipped,
    )


def run_groups(
    groups: list[MatchGroup],
    client: LlmClient,
    settings: LlmERSettings,
    *,
    apply: bool,
    force: bool,
    candidate_collection: Any | None = None,
    report: LlmERReport | None = None,
) -> list[GroupResult]:
    decision_counts: Counter[str] = Counter()
    final_counts: Counter[str] = Counter()
    update_counts: Counter[str] = Counter()
    mongo_modified = mongo_skipped = 0

    if apply and candidate_collection is None:
        raise ValueError("candidate_collection is required when apply=True.")

    configured_concurrency = settings.llm_concurrency
    concurrency = min(configured_concurrency, len(groups)) if groups else 1
    processed_groups: list[_ProcessedGroup] = []

    if concurrency <= 1:
        processed_groups = [
            _process_group(
                index,
                group,
                client,
                settings,
                apply=apply,
                force=force,
                candidate_collection=candidate_collection,
            )
            for index, group in enumerate(groups)
        ]
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(
                    _process_group,
                    index,
                    group,
                    client,
                    settings,
                    apply=apply,
                    force=force,
                    candidate_collection=candidate_collection,
                )
                for index, group in enumerate(groups)
            ]
            processed_groups = [future.result() for future in as_completed(futures)]
        processed_groups.sort(key=lambda item: item.index)

    results: list[GroupResult] = []
    for processed in processed_groups:
        result = processed.result
        results.append(result)
        decision_counts[result.llm_decision.value] += 1
        final_counts[result.final_decision.value] += 1
        update_counts.update(processed.update_counts)
        mongo_modified += processed.mongo_modified
        mongo_skipped += processed.mongo_skipped

    if report is not None:
        report.llm_calls = len(groups)
        report.concurrency = configured_concurrency
        report.decision_counts = dict(sorted(decision_counts.items()))
        report.final_decision_counts = dict(sorted(final_counts.items()))
        report.candidate_update_counts = dict(sorted(update_counts.items()))
        report.mongo_modified = mongo_modified
        report.mongo_skipped_existing = mongo_skipped
    return results


def open_llm_collections(settings: LlmERSettings) -> tuple[Any, Any, Any, Any, Any]:
    """Open (client, google, tripadvisor, thefork, candidates), failing fast."""
    from pymongo import MongoClient

    client: Any = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except PyMongoError:
        client.close()
        raise
    db = client[settings.mongo_db]
    return (
        client,
        db[settings.google_collection],
        db[settings.tripadvisor_collection],
        db[settings.thefork_collection],
        db[settings.candidates_collection],
    )
