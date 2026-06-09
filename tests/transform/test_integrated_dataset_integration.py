"""Integration test against a real MongoDB for the production bulk_write path.

It auto-skips when MongoDB is not reachable. To run it locally:

    docker compose up -d mongo
    uv run pytest tests/transform/test_integrated_dataset_integration.py
"""

import os
import uuid

import pytest

pymongo = pytest.importorskip("pymongo")
from pymongo.errors import PyMongoError  # noqa: E402

from transform.integrated_dataset.config import IntegratedSettings  # noqa: E402
from transform.integrated_dataset.transform import build_collections  # noqa: E402

MONGO_URI = os.environ.get("DATAMAN_MONGO_URI", "mongodb://localhost:27017")


@pytest.fixture()
def mongo_db():
    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
    try:
        client.admin.command("ping")
    except PyMongoError:
        client.close()
        pytest.skip(f"MongoDB not reachable at {MONGO_URI}; skipping integration test")

    db_name = f"dataman_int_test_{uuid.uuid4().hex[:16]}"
    try:
        yield client[db_name]
    finally:
        client.drop_database(db_name)
        client.close()


def test_build_collections_uses_real_mongo_bulk_write_path(mongo_db):
    mongo_db.google.insert_one(
        {
            "_id": "g1",
            "place_id": "g1",
            "name": "Da Mario",
            "address": "Via Roma, 1, Milano",
            "latitude": 45.0,
            "longitude": 9.0,
            "rating": 4.4,
            "review_count": 100,
            "is_dining": True,
            "is_operational": True,
        }
    )
    mongo_db.ta.insert_one(
        {
            "_id": "https://www.tripadvisor.it/Restaurant_Review-dta1.html",
            "ta_location_id": "ta1",
            "restaurant_name": "Da Mario",
            "rating": 4.5,
            "total_review": 90,
        }
    )
    mongo_db.candidates.insert_one(
        {
            "_id": "g1:ta1",
            "google_id": "g1",
            "source": "tripadvisor",
            "source_id": "ta1",
            "label": "UNCERTAIN",
            "llm_label": "MATCH",
            "score": 0.61,
            "dmin": 0.58,
            "dmax": 0.63,
            "block_source": "geo",
            "fast_path": None,
            "is_chain": False,
            "chain_brand": None,
            "chain_hardening": [],
            "components": {"geo_dist_m": 20.0, "name_sim": 0.92},
        }
    )

    report = build_collections(
        mongo_db.google,
        mongo_db.ta,
        mongo_db.tf,
        mongo_db.candidates,
        mongo_db.links,
        mongo_db.integrated,
        IntegratedSettings(_env_file=None, batch_size=1),
        replace_destination=True,
    )

    assert report.links_written == 1
    assert report.integrated_written == 1
    assert mongo_db.links.find_one({"_id": "tripadvisor:g1:ta1"})["match_method"] == "llm"
    integrated = mongo_db.integrated.find_one({"_id": "g1"})
    assert integrated["has_tripadvisor"] is True
    assert integrated["tripadvisor_location_id"] == "ta1"
