from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CleanSettings(BaseSettings):
    """Settings for the Google Places clean transform.

    Follows the project's ``DATAMAN_`` env convention and, like the load layer, has
    **no required fields** — in particular no Google Places API key (that was only
    needed at extract time). Mongo -> Mongo: raw source, clean destination.

    There are **no Nominatim/geocoding settings**: Google coordinates are authoritative
    and copied verbatim, never recomputed.

    **Env-collision note:** the Mongo fields use the shared ``DATAMAN_`` prefix (one
    Mongo deployment), so ``DATAMAN_SOURCE_COLLECTION`` / ``DATAMAN_DESTINATION_COLLECTION``
    are *shared* with the other transform services. Exporting them in a shared ``.env``
    would point this service at non-Google collections — rely on the per-service defaults
    below and only override deliberately. ``clean_collection`` guards against source ==
    destination.
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
    source_collection: str = "restaurants_raw_google"
    destination_collection: str = "restaurants_clean_google"

    # Transform knobs.
    low_review_threshold: int = Field(default=10, ge=0)  # flag only; records are not removed
    batch_size: int = Field(default=1000, gt=0)
    # Default: flag relevance/junk, don't delete (mirrors the low-review decision).
    drop_non_dining: bool = False
    # Drop the inert placeholders: a geographic-name record that also has no rating
    # (unusable name + nothing to compare). The raw collection still retains them.
    drop_junk: bool = True
