from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ERSettings(BaseSettings):
    """Settings for the entity-resolution transform.

    Follows the project's shared ``DATAMAN_`` environment convention. Mongo collection
    names are explicit per input source because this transform reads three clean
    collections and writes one candidate collection.
    """

    model_config = SettingsConfigDict(
        env_prefix="DATAMAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MongoDB (Mongo -> Mongo: clean source collections, candidate destination).
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "dataman"
    source_collection_google: str = "restaurants_clean_google"
    source_collection_tripadvisor: str = "restaurants_clean_tripadvisor"
    source_collection_thefork: str = "restaurants_clean_thefork"
    destination_collection: str = "entity_resolution_candidates"

    # ER knobs.
    dmin: float = Field(default=0.40, ge=0.0, le=1.0)
    dmax: float = Field(default=0.85, ge=0.0, le=1.0)
    dmin_tripadvisor: float | None = Field(default=None, ge=0.0, le=1.0)
    dmax_tripadvisor: float | None = Field(default=None, ge=0.0, le=1.0)
    dmin_thefork: float | None = Field(default=None, ge=0.0, le=1.0)
    dmax_thefork: float | None = Field(default=None, ge=0.0, le=1.0)
    dmin_chain_tripadvisor: float | None = Field(default=None, ge=0.0, le=1.0)
    dmax_chain_tripadvisor: float | None = Field(default=None, ge=0.0, le=1.0)
    dmin_chain_thefork: float | None = Field(default=None, ge=0.0, le=1.0)
    dmax_chain_thefork: float | None = Field(default=None, ge=0.0, le=1.0)
    geo_block_radius_m: float = Field(default=150.0, gt=0.0)
    chain_auto_match_radius_m: float = Field(default=75.0, gt=0.0)
    batch_size: int = Field(default=1000, gt=0)

    @model_validator(mode="after")
    def _thresholds_ordered(self) -> ERSettings:
        self.validate_thresholds()
        return self

    def thresholds_for_source(
        self,
        source: str,
        *,
        is_chain: bool = False,
    ) -> tuple[float, float]:
        """Return effective thresholds with chain -> source -> global fallback."""
        if source == "tripadvisor":
            source_dmin = self.dmin if self.dmin_tripadvisor is None else self.dmin_tripadvisor
            source_dmax = self.dmax if self.dmax_tripadvisor is None else self.dmax_tripadvisor
            if is_chain:
                return (
                    source_dmin
                    if self.dmin_chain_tripadvisor is None
                    else self.dmin_chain_tripadvisor,
                    source_dmax
                    if self.dmax_chain_tripadvisor is None
                    else self.dmax_chain_tripadvisor,
                )
            return source_dmin, source_dmax
        if source == "thefork":
            source_dmin = self.dmin if self.dmin_thefork is None else self.dmin_thefork
            source_dmax = self.dmax if self.dmax_thefork is None else self.dmax_thefork
            if is_chain:
                return (
                    source_dmin if self.dmin_chain_thefork is None else self.dmin_chain_thefork,
                    source_dmax if self.dmax_chain_thefork is None else self.dmax_chain_thefork,
                )
            return source_dmin, source_dmax
        return self.dmin, self.dmax

    def validate_thresholds(self) -> None:
        """Validate global and effective per-source threshold ordering."""
        if self.dmin >= self.dmax:
            raise ValueError("dmin must be lower than dmax.")
        for source in ("tripadvisor", "thefork"):
            dmin, dmax = self.thresholds_for_source(source)
            if dmin >= dmax:
                raise ValueError(f"{source} dmin must be lower than dmax.")
            dmin_chain, dmax_chain = self.thresholds_for_source(source, is_chain=True)
            if dmin_chain >= dmax_chain:
                raise ValueError(f"chain {source} dmin must be lower than dmax.")
