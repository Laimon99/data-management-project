from __future__ import annotations

DECISION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["MATCH", "NON_MATCH", "UNCERTAIN"]},
        "matched_candidate_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
        "risk_flags": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "chain_branch_ambiguity",
                    "address_mismatch",
                    "name_mismatch",
                    "large_distance",
                    "multiple_plausible_candidates",
                    "missing_coordinates",
                    "insufficient_evidence",
                ],
            },
        },
    },
    "required": [
        "decision",
        "matched_candidate_id",
        "confidence",
        "reason",
        "risk_flags",
    ],
    "additionalProperties": False,
}


def response_text_format() -> dict:
    return {
        "format": {
            "type": "json_schema",
            "name": "entity_resolution_llm_decision",
            "strict": True,
            "schema": DECISION_JSON_SCHEMA,
        }
    }
