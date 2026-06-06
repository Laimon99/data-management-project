from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CleanSettings(BaseSettings):
    """Settings for the Tripadvisor clean+geocode transform.

    Follows the project's ``DATAMAN_`` env convention and, like the load layer,
    has **no required fields** — in particular no Google Places API key. Mongo
    fields are shared with the load layer; Nominatim fields are carried over from
    the former geocode service. Nominatim defaults respect the usage policy
    (>= 1 request/second, descriptive user agent).
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
    source_collection: str = "restaurants_raw_tripadvisor"
    destination_collection: str = "restaurants_clean_tripadvisor"

    # Transform knobs.
    low_review_threshold: int = 10  # informational count only; records are not removed
    batch_size: int = 1000

    # Nominatim geocoding.
    delay_seconds: float = 1.2  # >= 1s is mandatory per the Nominatim ToS
    timeout: int = 10
    max_retries: int = 2
    user_agent: str = "dataman_restaurant_geocoder_milan/1.0 (transform)"

    @field_validator("delay_seconds")
    @classmethod
    def _enforce_min_delay(cls, value: float) -> float:
        """Settings-level guard so env (DATAMAN_DELAY_SECONDS) cannot bypass the
        Nominatim usage policy the way the CLI's --delay check does."""
        if value < 1.0:
            raise ValueError("delay_seconds must be >= 1.0 (Nominatim usage policy).")
        return value
