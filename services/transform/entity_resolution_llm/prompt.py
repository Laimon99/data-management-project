from __future__ import annotations

import json

from .models import CandidateVenue, MatchGroup

SYSTEM_MESSAGE = """You are an entity-resolution assistant for restaurant records.

Your task is to decide whether a source venue from Tripadvisor or TheFork matches one
Google Places candidate. Use only the provided data. Do not search the web, do not infer
facts not present in the input, and do not create new records.

Prefer UNCERTAIN over MATCH when evidence is incomplete, when multiple candidates are
plausible, or when the venue is a chain/branch-heavy brand. Name similarity alone is not
enough: address, street number, postal code, distance, phone, and website evidence are
stronger. Ratings and review counts are weak context.

Return only valid JSON matching the required schema."""


def candidate_sort_key(candidate: CandidateVenue) -> tuple[float, float, float, float]:
    score = candidate.score if candidate.score is not None else -1.0
    distance = candidate.distance_m if candidate.distance_m is not None else 1_000_000.0
    name_sim = float(candidate.components.get("name_sim") or 0.0)
    street_sim = float(candidate.components.get("street_sim") or 0.0)
    return (-score, distance, -name_sim, -street_sim)


def top_candidates(candidates: list[CandidateVenue], max_candidates: int) -> list[CandidateVenue]:
    return sorted(candidates, key=candidate_sort_key)[:max_candidates]


def build_messages(group: MatchGroup) -> list[dict[str, str]]:
    payload = {
        "task": "Resolve one source venue against the provided Google Places candidates.",
        "allowed_decisions": ["MATCH", "NON_MATCH", "UNCERTAIN"],
        "source_venue": group.source_venue.model_dump(mode="json"),
        "candidate_google_places": [
            candidate.model_dump(mode="json") for candidate in group.candidates
        ],
        "candidate_count_note": {
            "shown": len(group.candidates),
            "total_uncertain_candidates_for_source": group.total_candidate_count,
        },
        "decision_guidance": [
            "Return MATCH only when exactly one candidate is clearly the same physical restaurant.",
            "Return NON_MATCH when none of the shown candidates plausibly match.",
            "Return UNCERTAIN when evidence is insufficient or multiple candidates are plausible.",
            "If choosing MATCH, matched_candidate_id must be one of the shown candidate ids.",
        ],
    }
    return [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]
