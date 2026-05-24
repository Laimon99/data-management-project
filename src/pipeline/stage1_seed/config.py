from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DATAMAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    google_places_api_key: SecretStr

    milan_center_lat: float = 45.4642
    milan_center_lon: float = 9.1900
    search_radius_m: int = 300
    outer_radius_m: int = 9000
    tile_overlap: float = 0.2

    included_types: list[str] = Field(
        default_factory=lambda: [
            "restaurant",
            "cafe",
            "bar",
            "bakery",
            "meal_delivery",
            "meal_takeaway",
            "food_court",
            "fast_food_restaurant",
            "pizza_restaurant",
            "coffee_shop",
        ]
    )

    max_pages_per_tile: int = 3
    request_delay_s: float = 0.1
    request_timeout_s: float = 30.0

    seed_store_backend: Literal["jsonl", "mongo"] = "jsonl"
    seed_jsonl_path: Path = Path("data/restaurants_seed.jsonl")
    checkpoint_dir: Path = Path("data/checkpoints")

    mongo_uri: str | None = None
    mongo_db: str = "dataman"
    mongo_collection: str = "restaurants_seed"
