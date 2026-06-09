from pydantic_settings import BaseSettings, SettingsConfigDict


class ClickHouseLoaderSettings(BaseSettings):
    """Settings for the ClickHouse load layer.

    Follows the project's ``DATAMAN_`` env convention. No required fields —
    all defaults work for the standard local Docker Compose setup.
    """

    model_config = SettingsConfigDict(
        env_prefix="DATAMAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MongoDB source side
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "dataman"

    # ClickHouse destination side
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_db: str = "dataman"
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
