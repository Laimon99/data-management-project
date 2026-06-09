from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Decision(StrEnum):
    MATCH = "MATCH"
    NON_MATCH = "NON_MATCH"
    UNCERTAIN = "UNCERTAIN"


class RiskFlag(StrEnum):
    CHAIN_BRANCH_AMBIGUITY = "chain_branch_ambiguity"
    ADDRESS_MISMATCH = "address_mismatch"
    NAME_MISMATCH = "name_mismatch"
    LARGE_DISTANCE = "large_distance"
    MULTIPLE_PLAUSIBLE_CANDIDATES = "multiple_plausible_candidates"
    MISSING_COORDINATES = "missing_coordinates"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class SourceVenue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["tripadvisor", "thefork"]
    source_id: str
    name: str | None = None
    address: str | None = None
    street: str | None = None
    house_number: str | None = None
    postal_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    phone: str | None = None
    website: str | None = None
    rating: float | None = None
    review_count: int | None = None
    cuisines: list[str] = Field(default_factory=list)


class CandidateVenue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    google_id: str
    name: str | None = None
    address: str | None = None
    street: str | None = None
    house_number: str | None = None
    postal_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    phone: str | None = None
    website: str | None = None
    rating: float | None = None
    review_count: int | None = None
    cuisines: list[str] = Field(default_factory=list)
    score: float | None = Field(default=None, ge=0, le=1)
    dmin: float | None = Field(default=None, ge=0, le=1)
    dmax: float | None = Field(default=None, ge=0, le=1)
    block_source: str | None = None
    fast_path: str | None = None
    is_chain: bool = False
    chain_brand: str | None = None
    chain_hardening: list[str] = Field(default_factory=list)
    components: dict[str, Any] = Field(default_factory=dict)

    @property
    def distance_m(self) -> float | None:
        value = self.components.get("geo_dist_m")
        return float(value) if value is not None else None


class MatchGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    source_venue: SourceVenue
    candidates: list[CandidateVenue]
    total_candidate_count: int

    @field_validator("candidates")
    @classmethod
    def _candidate_ids_must_be_unique(cls, value: list[CandidateVenue]) -> list[CandidateVenue]:
        ids = [candidate.candidate_id for candidate in value]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate_id values must be unique within a group.")
        return value


class LlmDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Decision
    matched_candidate_id: str | None
    confidence: float = Field(ge=0, le=1)
    reason: str
    risk_flags: list[RiskFlag] = Field(default_factory=list)

    @field_validator("matched_candidate_id")
    @classmethod
    def _blank_candidate_is_null(cls, value: str | None) -> str | None:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


class GroupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    source: Literal["tripadvisor", "thefork"]
    source_id: str
    llm_model: str
    llm_decision: Decision
    final_decision: Decision
    matched_candidate_id: str | None
    confidence: float = Field(ge=0, le=1)
    reason: str
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    validation_notes: list[str] = Field(default_factory=list)
    candidate_updates: dict[str, Decision] = Field(default_factory=dict)
    prompt_version: str
    input_hash: str
    prompt_candidate_count: int
    total_candidate_count: int
