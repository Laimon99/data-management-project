from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Neighbourhood(BaseModel):
    name: str
    lat: float
    lon: float
    outer_radius_m: int


def _default_neighbourhoods() -> list[Neighbourhood]:
    return [
        Neighbourhood(name="duomo", lat=45.4642, lon=9.1900, outer_radius_m=1200),
        Neighbourhood(name="navigli_1", lat=45.4520, lon=9.1760, outer_radius_m=600),
        Neighbourhood(name="navigli_2", lat=45.4485, lon=9.1720, outer_radius_m=600),
        Neighbourhood(name="navigli_3", lat=45.4450, lon=9.1680, outer_radius_m=600),
        Neighbourhood(name="brera", lat=45.4720, lon=9.1880, outer_radius_m=600),
        Neighbourhood(name="isola", lat=45.4870, lon=9.1880, outer_radius_m=600),
        Neighbourhood(name="porta_venezia_1", lat=45.4740, lon=9.2050, outer_radius_m=600),
        Neighbourhood(name="porta_venezia_2", lat=45.4790, lon=9.2110, outer_radius_m=600),
        Neighbourhood(name="porta_romana_1", lat=45.4540, lon=9.2010, outer_radius_m=600),
        Neighbourhood(name="porta_romana_2", lat=45.4490, lon=9.2050, outer_radius_m=600),
        Neighbourhood(name="sempione_1", lat=45.4790, lon=9.1740, outer_radius_m=600),
        Neighbourhood(name="sempione_2", lat=45.4830, lon=9.1680, outer_radius_m=600),
        Neighbourhood(name="sempione_3", lat=45.4870, lon=9.1620, outer_radius_m=600),
        Neighbourhood(name="loreto", lat=45.4860, lon=9.2160, outer_radius_m=600),
    ]


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

    neighbourhoods: list[Neighbourhood] = Field(default_factory=_default_neighbourhoods)

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
    seed_jsonl_path: Path = Path("data/raw/google_places/restaurants_seed.jsonl")
    checkpoint_dir: Path = Path("data/raw/google_places/checkpoints")

    mongo_uri: str | None = None
    mongo_db: str = "dataman"
    mongo_collection: str = "restaurants_seed"
