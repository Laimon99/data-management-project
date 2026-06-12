from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class AnalysisSettings(BaseSettings):
    """Settings for the read-only analytics layer.

    Mirrors ``load.clickhouse.config.ClickHouseLoaderSettings`` so the notebook
    reads the same ``DATAMAN_CLICKHOUSE_*`` env vars (and ``.env``) as the
    loader. No required fields — the defaults match the standard local Docker
    Compose setup.
    """

    model_config = SettingsConfigDict(
        env_prefix="DATAMAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_db: str = "dataman"
    clickhouse_user: str = "default"
    clickhouse_password: str = ""


def clickhouse_client(settings: AnalysisSettings | None = None) -> Any:
    """Open a ClickHouse client for read-only querying.

    Mirrors ``load.clickhouse.loader.open_clickhouse`` but does **not** create
    or mutate any database — it selects the existing analytics DB and issues a
    cheap ``SELECT 1`` to fail fast with a clear message if ClickHouse is
    unreachable. The import lives inside the function so tests need not have a
    live client installed.
    """
    import clickhouse_connect  # type: ignore[import]

    settings = settings or AnalysisSettings()
    try:
        client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_db,
        )
        client.command("SELECT 1")
    except Exception as exc:  # pragma: no cover - exercised only with a live DB
        raise RuntimeError(
            "Could not connect to ClickHouse at "
            f"{settings.clickhouse_host}:{settings.clickhouse_port} "
            f"(db={settings.clickhouse_db}). Start the analytics layer with "
            "`docker compose --profile analytics up -d clickhouse` and load it "
            "with `uv run dataman-load-clickhouse all`."
        ) from exc
    return client
