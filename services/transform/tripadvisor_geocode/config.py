from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Sentinel used for missing coordinates, matching the raw scraper's NaN strings.
NAN_VALUE = "NaN"

# Default input/output live alongside the rest of the Tripadvisor raw data.
RAW_DIR = Path("data/raw/tripadvisor")
DEFAULT_INPUT = RAW_DIR / "tripadvisor_scraper_results.json"
DEFAULT_OUTPUT = RAW_DIR / "tripadvisor_scraper_results_geocoded.json"


class GeocodeSettings(BaseSettings):
    """Settings for the Tripadvisor geocoding enrichment.

    Follows the project's ``DATAMAN_`` env convention. Defaults respect the
    Nominatim usage policy (>= 1 request/second, descriptive user agent).
    """

    model_config = SettingsConfigDict(
        env_prefix="DATAMAN_GEOCODE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # >= 1 s is mandatory per the Nominatim terms of service.
    delay_seconds: float = 1.2
    # Per-request HTTP timeout, in seconds.
    timeout: int = 10
    # Retries on transient network/timeout errors.
    max_retries: int = 2
    user_agent: str = "dataman_restaurant_geocoder_milan/1.0 (geocoding-enrichment)"
