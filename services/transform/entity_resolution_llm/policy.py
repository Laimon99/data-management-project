from __future__ import annotations

import hashlib
import json
from typing import Any

from .config import LlmERSettings
from .models import CandidateVenue, Decision, GroupResult, LlmDecision, MatchGroup, RiskFlag


def input_hash(group: MatchGroup) -> str:
    encoded = json.dumps(
        group.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _has_contact_match(candidate: CandidateVenue) -> bool:
    components = candidate.components
    return (
        float(components.get("phone_match") or 0.0) == 1.0
        or float(components.get("website_match") or 0.0) == 1.0
        or candidate.fast_path in {"phone", "website"}
    )


def _distance(candidate: CandidateVenue) -> float | None:
    return candidate.distance_m


def apply_policy(
    group: MatchGroup,
    decision: LlmDecision,
    settings: LlmERSettings,
    *,
    model: str,
) -> GroupResult:
    candidate_by_id = {candidate.candidate_id: candidate for candidate in group.candidates}
    matched = (
        candidate_by_id.get(decision.matched_candidate_id)
        if decision.matched_candidate_id is not None
        else None
    )
    final_decision = decision.decision
    notes: list[str] = []

    if decision.decision == Decision.MATCH:
        if matched is None:
            final_decision = Decision.UNCERTAIN
            notes.append("downgraded: matched_candidate_id is missing or not in prompt candidates")
        elif decision.confidence < settings.match_confidence_threshold:
            final_decision = Decision.UNCERTAIN
            notes.append(
                "downgraded: confidence below "
                f"{settings.match_confidence_threshold:.2f}"
            )
        elif {str(flag) for flag in decision.risk_flags} & settings.severe_risk_flags:
            final_decision = Decision.UNCERTAIN
            notes.append("downgraded: severe risk flag present")

        if matched is not None:
            distance = _distance(matched)
            contact_match = _has_contact_match(matched)
            if distance is None and not contact_match:
                final_decision = Decision.UNCERTAIN
                notes.append("downgraded: missing distance without phone/website evidence")
            elif distance is not None and distance > settings.contact_override_distance_m:
                final_decision = Decision.UNCERTAIN
                notes.append("downgraded: distance exceeds contact override threshold")
            elif (
                distance is not None
                and distance > settings.max_match_distance_m
                and not contact_match
            ):
                final_decision = Decision.UNCERTAIN
                notes.append("downgraded: distance exceeds max threshold without contact evidence")
            elif (
                distance is not None
                and distance > settings.large_distance_m
                and not contact_match
            ):
                final_decision = Decision.UNCERTAIN
                notes.append("downgraded: large distance without contact evidence")

    candidate_updates: dict[str, Decision] = {}
    if final_decision == Decision.MATCH and matched is not None:
        for candidate in group.candidates:
            candidate_updates[candidate.candidate_id] = (
                Decision.MATCH
                if candidate.candidate_id == matched.candidate_id
                else Decision.NON_MATCH
            )
    elif final_decision == Decision.NON_MATCH:
        candidate_updates = {
            candidate.candidate_id: Decision.NON_MATCH for candidate in group.candidates
        }

    risk_flags = list(decision.risk_flags)
    if final_decision == Decision.UNCERTAIN and not risk_flags and notes:
        risk_flags.append(RiskFlag.INSUFFICIENT_EVIDENCE)

    matched_candidate_id = (
        matched.candidate_id if matched and final_decision == Decision.MATCH else None
    )

    return GroupResult(
        group_id=group.group_id,
        source=group.source_venue.source,
        source_id=group.source_venue.source_id,
        llm_model=model,
        llm_decision=decision.decision,
        final_decision=final_decision,
        matched_candidate_id=matched_candidate_id,
        confidence=decision.confidence,
        reason=decision.reason,
        risk_flags=risk_flags,
        validation_notes=notes,
        candidate_updates=candidate_updates,
        prompt_version=settings.prompt_version,
        input_hash=input_hash(group),
        prompt_candidate_count=len(group.candidates),
        total_candidate_count=group.total_candidate_count,
    )


def result_to_json(result: GroupResult) -> dict[str, Any]:
    return result.model_dump(mode="json")
