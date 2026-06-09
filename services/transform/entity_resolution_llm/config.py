from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LlmERSettings(BaseSettings):
    """Settings for LLM adjudication of ER candidates."""

    model_config = SettingsConfigDict(
        env_prefix="DATAMAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "dataman"
    candidates_collection: str = "entity_resolution_candidates"
    google_collection: str = "restaurants_clean_google"
    tripadvisor_collection: str = "restaurants_clean_tripadvisor"
    thefork_collection: str = "restaurants_clean_thefork"

    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout_seconds: float = Field(default=30.0, gt=0)
    openai_max_retries: int = Field(default=5, ge=0)
    openai_retry_initial_seconds: float = Field(default=2.0, gt=0)
    openai_retry_max_seconds: float = Field(default=30.0, gt=0)
    llm_match_model: str = "gpt-5.4-mini"
    llm_concurrency: int = Field(default=1, ge=1, le=16)
    prompt_version: str = "v1"

    max_candidates: int = Field(default=5, ge=1, le=10)
    match_confidence_threshold: float = Field(default=0.85, ge=0, le=1)
    large_distance_m: float = Field(default=150.0, gt=0)
    max_match_distance_m: float = Field(default=300.0, gt=0)
    contact_override_distance_m: float = Field(default=1000.0, gt=0)
    severe_risk_flags_csv: str = (
        "chain_branch_ambiguity,address_mismatch,large_distance,"
        "multiple_plausible_candidates"
    )

    @property
    def severe_risk_flags(self) -> set[str]:
        return {
            flag.strip()
            for flag in self.severe_risk_flags_csv.split(",")
            if flag.strip()
        }
