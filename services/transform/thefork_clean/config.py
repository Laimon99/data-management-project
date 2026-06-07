from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CleanSettings(BaseSettings):
    """Settings for the TheFork clean transform.

    Follows the project's ``DATAMAN_`` env convention and, like the load layer and the
    other two transforms, has **no required fields** (no scraper/API secrets — those were
    only needed at extract time). Mongo -> Mongo: raw source, clean destination.

    There are **no geocoding settings** (TheFork coordinates are authoritative and copied
    verbatim) and **no relevance/drop settings** (the slice is 100% Milan restaurants and
    duplicate-free — nothing is filtered or de-duplicated; flags are count-only).

    **Env-collision note:** the Mongo fields use the shared ``DATAMAN_`` prefix, so
    ``DATAMAN_SOURCE_COLLECTION`` / ``DATAMAN_DESTINATION_COLLECTION`` are *shared* with the
    other transform services. Rely on the per-service defaults below and only override
    deliberately. ``clean_collection`` guards against source == destination.
    """

    model_config = SettingsConfigDict(
        env_prefix="DATAMAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MongoDB (Mongo -> Mongo: raw source, clean destination).
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "dataman"
    source_collection: str = "restaurants_raw_thefork"
    destination_collection: str = "restaurants_clean_thefork"

    # Transform knobs.
    low_review_threshold: int = Field(default=10, ge=0)  # flag only; records are not removed
    review_cap: int = Field(default=15, gt=0)  # max nested reviews kept (scraper cap is 15)
    batch_size: int = Field(default=1000, gt=0)
