from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IntegrationAssessmentSettings(BaseSettings):
    """Settings for the post-integration assessment service."""

    model_config = SettingsConfigDict(
        env_prefix="DATAMAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "dataman"

    candidate_collection: str = "entity_resolution_candidates"
    links_collection: str = "entity_resolution_links"
    integrated_collection: str = "restaurants_integrated"
    google_collection: str = "restaurants_clean_google"
    tripadvisor_collection: str = "restaurants_clean_tripadvisor"
    thefork_collection: str = "restaurants_clean_thefork"

    output_dir: Path = Path("data/quality/integration_assessment")
    markdown_report: Path = Path("docs/post-integration-assessment.md")
    latex_tables_dir: Path = Path("report/post_integration/tables")
    cv_folds: int = Field(default=5, ge=2)
    cv_seed: int = 42
    distance_buckets_m: tuple[int, ...] = (50, 100, 250)

    default_in_calibration_gold_csvs: tuple[Path, ...] = (
        Path("data/quality/entity_resolution_calibration_normal.csv"),
        Path("data/quality/entity_resolution_calibration_chains.csv"),
    )
    default_in_calibration_gold_globs: tuple[str, ...] = ()
    default_gold_globs: tuple[str, ...] = (
        "data/quality/integration_assessment/integration_gold*.csv",
        "data/quality/integration_assessment/*post_int*gold*.csv",
    )

    def resolve_gold_paths(self, explicit_paths: list[Path] | None = None) -> list[Path]:
        """Return explicit evaluation/holdout gold paths, or discovered expansion files."""
        if explicit_paths:
            return list(explicit_paths)

        return self._resolve_default_paths((), self.default_gold_globs)

    def resolve_in_calibration_gold_paths(
        self, explicit_paths: list[Path] | None = None
    ) -> list[Path]:
        """Return calibration/train gold CSV paths."""
        if explicit_paths:
            return list(explicit_paths)

        return self._resolve_default_paths(
            self.default_in_calibration_gold_csvs,
            self.default_in_calibration_gold_globs,
        )

    @staticmethod
    def _resolve_default_paths(csvs: tuple[Path, ...], globs: tuple[str, ...]) -> list[Path]:
        paths: list[Path] = [path for path in csvs if path.exists()]
        seen = {path.resolve() for path in paths}
        for pattern in globs:
            for path in sorted(Path().glob(pattern)):
                resolved = path.resolve()
                if path.is_file() and resolved not in seen:
                    paths.append(path)
                    seen.add(resolved)
        return paths
