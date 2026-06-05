from pydantic_settings import BaseSettings, SettingsConfigDict


class LoaderSettings(BaseSettings):
    """Settings for the Load layer.

    Mirrors the project's ``DATAMAN_`` env convention but, unlike the extractor
    packages, has **no required fields** — crucially no Google Places API key.
    """

    model_config = SettingsConfigDict(
        env_prefix="DATAMAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "dataman"
