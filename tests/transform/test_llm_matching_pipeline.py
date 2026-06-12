import mongomock

from transform.entity_resolution_llm.config import LlmERSettings
from transform.llm_matching_pipeline.transform import run_pipeline_collections


def _db():
    return mongomock.MongoClient()["dataman"]


def _llm_settings(**overrides):
    return LlmERSettings(_env_file=None, **overrides)


def _google(place_id="g1", **overrides):
    doc = {
        "_id": place_id,
        "place_id": place_id,
        "name": "Da Mario",
        "address": "Via Roma, 1, Milano",
        "latitude": 45.0,
        "longitude": 9.0,
        "rating": 4.5,
        "review_count": 100,
        "is_dining": True,
        "is_operational": True,
    }
    doc.update(overrides)
    return doc


def _ta(source_id="ta1", **overrides):
    doc = {
        "_id": f"https://www.tripadvisor.it/Restaurant_Review-d{source_id}.html",
        "ta_location_id": source_id,
        "restaurant_name": "Da Mario",
        "address": "Via Roma 1, Milano",
        "latitude": 45.0,
        "longitude": 9.0,
        "rating": 4.5,
        "total_review": 80,
    }
    doc.update(overrides)
    return doc


def _candidate(**overrides):
    doc = {
        "_id": "g1:ta1",
        "google_id": "g1",
        "source": "tripadvisor",
        "source_id": "ta1",
        "label": "UNCERTAIN",
        "llm_label": None,
        "score": 0.61,
        "dmin": 0.58,
        "dmax": 0.63,
        "block_source": "geo",
        "fast_path": None,
        "is_chain": False,
        "chain_brand": None,
        "chain_hardening": [],
        "components": {"phone_match": 1.0, "geo_dist_m": 20.0, "name_sim": 0.9},
    }
    doc.update(overrides)
    return doc


def test_pipeline_mock_apply_writes_llm_label():
    db = _db()
    db.google.insert_one(_google())
    db.ta.insert_one(_ta())
    db.candidates.insert_one(_candidate())

    report = run_pipeline_collections(
        db.google,
        db.ta,
        db.tf,
        db.candidates,
        _llm_settings(),
        mode="mock",
        apply=True,
    )

    assert report.llm.mongo_modified == 1
    assert db.candidates.find_one({"_id": "g1:ta1"})["llm_label"] == "MATCH"


def test_pipeline_dry_run_writes_nothing():
    db = _db()
    db.google.insert_one(_google())
    db.ta.insert_one(_ta())
    db.candidates.insert_one(_candidate())

    report = run_pipeline_collections(
        db.google,
        db.ta,
        db.tf,
        db.candidates,
        _llm_settings(),
        mode="dry-run",
        apply=False,
    )

    assert report.llm.groups == 1
    assert db.candidates.find_one({"_id": "g1:ta1"})["llm_label"] is None
