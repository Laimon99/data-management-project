import mongomock

from transform.entity_resolution_llm.client import MockLlmClient
from transform.entity_resolution_llm.config import LlmERSettings
from transform.entity_resolution_llm.models import Decision
from transform.entity_resolution_llm.transform import (
    LlmERReport,
    dry_run_records,
    load_groups,
    run_groups,
)


def _settings(**overrides):
    return LlmERSettings(_env_file=None, **overrides)


def _db():
    return mongomock.MongoClient()["dataman"]


def _google(place_id="g1", name="Da Mario", **overrides):
    doc = {
        "_id": place_id,
        "place_id": place_id,
        "name": name,
        "address": "Via Roma, 1, Milano",
        "street": "Via Roma",
        "house_number": "1",
        "postal_code": "20100",
        "latitude": 45.0,
        "longitude": 9.0,
        "phone": None,
        "website": None,
        "rating": 4.5,
        "review_count": 100,
        "cuisines": ["Italiano"],
    }
    doc.update(overrides)
    return doc


def _ta(source_id="ta1", name="Da Mario", **overrides):
    doc = {
        "_id": f"https://www.tripadvisor.it/Restaurant_Review-d{source_id}.html",
        "ta_location_id": source_id,
        "restaurant_name": name,
        "address": "Via Roma 1, Milano",
        "street": "Via Roma",
        "house_number": "1",
        "postal_code": "20100",
        "latitude": 45.0,
        "longitude": 9.0,
        "phone": None,
        "website": None,
        "rating": 4.5,
        "total_review": 80,
        "cuisines": ["Italiano"],
    }
    doc.update(overrides)
    return doc


def _tf(source_id="tf1", name="Da Mario", **overrides):
    doc = {
        "_id": f"da-mario-r{source_id}",
        "tf_id": source_id,
        "restaurant_name": name,
        "address": "Via Roma 1, Milano",
        "street": "Via Roma",
        "house_number": "1",
        "postal_code": "20100",
        "latitude": 45.0,
        "longitude": 9.0,
        "rating": 9.0,
        "review_count": 80,
        "cuisines": ["Italiano"],
    }
    doc.update(overrides)
    return doc


def _candidate(
    google_id="g1",
    source="tripadvisor",
    source_id="ta1",
    candidate_id=None,
    score=0.61,
    label="UNCERTAIN",
    **overrides,
):
    doc = {
        "_id": candidate_id or f"{google_id}:{source_id}",
        "google_id": google_id,
        "source": source,
        "source_id": source_id,
        "label": label,
        "llm_label": None,
        "score": score,
        "dmin": 0.58,
        "dmax": 0.63,
        "block_source": "geo",
        "fast_path": None,
        "is_chain": False,
        "chain_brand": None,
        "chain_hardening": [],
        "components": {
            "name_sim": 0.86,
            "geo_dist_m": 20.0,
            "geo_score": 0.96,
            "street_sim": 0.9,
            "phone_match": 0.0,
            "website_match": 0.0,
            "postal_code_match": 1.0,
        },
    }
    doc.update(overrides)
    return doc


def test_load_groups_reads_uncertain_candidates_and_joins_context():
    db = _db()
    db.google.insert_one(_google())
    db.ta.insert_one(_ta())
    db.candidates.insert_one(_candidate())
    report = LlmERReport(mode="dry-run", apply=False, force=False, source="all")

    groups = load_groups(
        db.google,
        db.ta,
        db.tf,
        db.candidates,
        _settings(),
        report=report,
    )

    assert report.read_candidates == 1
    assert report.groups == 1
    assert groups[0].group_id == "tripadvisor:ta1"
    assert groups[0].source_venue.name == "Da Mario"
    assert groups[0].candidates[0].candidate_id == "g1:ta1"


def test_load_groups_skips_existing_llm_label_unless_force():
    db = _db()
    db.google.insert_one(_google())
    db.ta.insert_one(_ta())
    db.candidates.insert_one(_candidate(llm_label="MATCH"))

    assert load_groups(db.google, db.ta, db.tf, db.candidates, _settings()) == []
    assert load_groups(db.google, db.ta, db.tf, db.candidates, _settings(), force=True)


def test_dry_run_records_include_messages_without_writing():
    db = _db()
    db.google.insert_one(_google())
    db.ta.insert_one(_ta())
    db.candidates.insert_one(_candidate())
    groups = load_groups(db.google, db.ta, db.tf, db.candidates, _settings())

    records = dry_run_records(groups, _settings())

    assert records[0]["messages"][0]["role"] == "system"
    assert records[0]["prompt_candidate_count"] == 1
    assert db.candidates.find_one({"_id": "g1:ta1"})["llm_label"] is None


def test_mock_match_apply_sets_match_and_non_match_labels():
    db = _db()
    db.google.insert_many(
        [
            _google("g1", phone="+39021234567"),
            _google("g2", name="Other", phone=None),
        ]
    )
    db.ta.insert_one(_ta(phone="+39021234567"))
    db.candidates.insert_many(
        [
            _candidate(
                "g1",
                candidate_id="g1:ta1",
                components={"phone_match": 1.0, "geo_dist_m": 30.0},
            ),
            _candidate(
                "g2",
                candidate_id="g2:ta1",
                score=0.50,
                components={"name_sim": 0.2, "geo_dist_m": 100.0, "street_sim": 0.2},
            ),
        ]
    )
    report = LlmERReport(mode="mock", apply=True, force=False, source="all")
    groups = load_groups(db.google, db.ta, db.tf, db.candidates, _settings(), report=report)

    results = run_groups(
        groups,
        MockLlmClient(),
        _settings(),
        apply=True,
        force=False,
        candidate_collection=db.candidates,
        report=report,
    )

    assert results[0].final_decision == Decision.MATCH
    assert db.candidates.find_one({"_id": "g1:ta1"})["llm_label"] == "MATCH"
    assert db.candidates.find_one({"_id": "g2:ta1"})["llm_label"] == "NON_MATCH"
    assert report.mongo_modified == 2
    assert report.candidate_update_counts == {"MATCH": 1, "NON_MATCH": 1}


def test_mock_uncertain_apply_writes_metadata_but_not_llm_label():
    db = _db()
    db.google.insert_many([_google("g1", name="Sushi One"), _google("g2", name="Sushi One")])
    db.ta.insert_one(_ta(name="Sushi One"))
    db.candidates.insert_many(
        [
            _candidate(
                "g1",
                candidate_id="g1:ta1",
                components={"name_sim": 0.85, "geo_dist_m": 20.0},
            ),
            _candidate(
                "g2",
                candidate_id="g2:ta1",
                score=0.60,
                components={"name_sim": 0.82, "geo_dist_m": 40.0},
            ),
        ]
    )
    report = LlmERReport(mode="mock", apply=True, force=False, source="all")
    groups = load_groups(db.google, db.ta, db.tf, db.candidates, _settings(), report=report)

    results = run_groups(
        groups,
        MockLlmClient(),
        _settings(),
        apply=True,
        force=False,
        candidate_collection=db.candidates,
        report=report,
    )

    assert results[0].final_decision == Decision.UNCERTAIN
    doc = db.candidates.find_one({"_id": "g1:ta1"})
    assert doc["llm_label"] is None
    assert doc["llm_status"] == "UNCERTAIN"
    assert doc["llm_final_decision"] == "UNCERTAIN"


def test_no_apply_does_not_modify_mongo():
    db = _db()
    db.google.insert_one(_google(phone="+39021234567"))
    db.ta.insert_one(_ta(phone="+39021234567"))
    db.candidates.insert_one(
        _candidate(components={"phone_match": 1.0, "geo_dist_m": 30.0})
    )
    groups = load_groups(db.google, db.ta, db.tf, db.candidates, _settings())

    run_groups(groups, MockLlmClient(), _settings(), apply=False, force=False)

    assert "llm_status" not in db.candidates.find_one({"_id": "g1:ta1"})
    assert db.candidates.find_one({"_id": "g1:ta1"})["llm_label"] is None
