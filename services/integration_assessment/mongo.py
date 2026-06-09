from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pymongo import MongoClient

from .config import IntegrationAssessmentSettings


@dataclass(frozen=True)
class IntegrationCollections:
    client: Any
    candidates: Any
    links: Any
    integrated: Any
    google: Any
    tripadvisor: Any
    thefork: Any


def open_collections(settings: IntegrationAssessmentSettings) -> IntegrationCollections:
    """Open and validate MongoDB collections needed by the assessment."""
    client = MongoClient(settings.mongo_uri)
    client.admin.command("ping")
    db = client[settings.mongo_db]
    return IntegrationCollections(
        client=client,
        candidates=db[settings.candidate_collection],
        links=db[settings.links_collection],
        integrated=db[settings.integrated_collection],
        google=db[settings.google_collection],
        tripadvisor=db[settings.tripadvisor_collection],
        thefork=db[settings.thefork_collection],
    )
