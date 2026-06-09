from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IntegratedSettings(BaseSettings):
    """Settings for resolved-link and integrated-dataset construction."""

    model_config = SettingsConfigDict(
        env_prefix="DATAMAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "dataman"
    google_collection: str = "restaurants_clean_google"
    tripadvisor_collection: str = "restaurants_clean_tripadvisor"
    thefork_collection: str = "restaurants_clean_thefork"
    candidates_collection: str = "entity_resolution_candidates"
    links_collection: str = "entity_resolution_links"
    integrated_collection: str = "restaurants_integrated"
    batch_size: int = Field(default=1000, gt=0)
