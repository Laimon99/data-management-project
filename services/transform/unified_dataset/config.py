from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class UnifiedSettings(BaseSettings):
    """Settings for the Stage-4 unified dataset transform.

    Mongo -> Mongo: reads clean source collections plus ER candidates, writes selected
    links and integrated restaurant documents. Collection names are explicit because this
    service has multiple inputs and outputs.
    """

    model_config = SettingsConfigDict(
        env_prefix="DATAMAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "dataman"

    source_collection_google: str = "restaurants_clean_google"
    source_collection_tripadvisor: str = "restaurants_clean_tripadvisor"
    source_collection_thefork: str = "restaurants_clean_thefork"
    candidate_collection: str = "entity_resolution_candidates"

    links_collection: str = "entity_resolution_links"
    integrated_collection: str = "restaurants_integrated"

    batch_size: int = Field(default=1000, gt=0)

    @model_validator(mode="after")
    def _outputs_do_not_collide_with_inputs(self) -> UnifiedSettings:
        inputs = {
            self.source_collection_google,
            self.source_collection_tripadvisor,
            self.source_collection_thefork,
            self.candidate_collection,
        }
        outputs = {self.links_collection, self.integrated_collection}
        collisions = inputs & outputs
        if collisions:
            joined = ", ".join(sorted(collisions))
            raise ValueError(f"output collection collides with an input collection: {joined}")
        if self.links_collection == self.integrated_collection:
            raise ValueError("links_collection and integrated_collection must differ.")
        return self
