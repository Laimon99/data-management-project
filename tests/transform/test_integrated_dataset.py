import mongomock

from transform.integrated_dataset.config import IntegratedSettings
from transform.integrated_dataset.transform import (
    _serial_replace,
    build_collections,
    select_links,
)


def _settings(**overrides):
    return IntegratedSettings(_env_file=None, **overrides)


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
        "city": "Milano",
        "latitude": 45.0,
        "longitude": 9.0,
        "rating": 4.5,
        "review_count": 100,
        "low_review": False,
        "flags": [],
        "phone": "+39021234567",
        "website": "https://damario.example",
        "price_level": 2,
        "photo_count": 5,
        "reviews": [{"text": "Good"}],
        "cuisines": ["Italian"],
        "is_dining": True,
        "is_operational": True,
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
        "city": "Milano",
        "latitude": 45.0,
        "longitude": 9.0,
        "rating": 4.5,
        "total_review": 80,
        "low_review": False,
        "flags": [],
        "phone": "+39021234567",
        "website": "https://damario.example",
        "email": "info@damario.example",
        "price_band": "€€",
        "photo_count": 3,
        "opening_hours": {"mon": "12:00-22:00"},
        "reviews": [{"text": "Nice"}],
        "cuisines": ["Italian"],
    }
    doc.update(overrides)
    return doc


def _tf(source_id="tf1", name="Da Mario", **overrides):
    doc = {
        "_id": f"da-mario-r{source_id}",
        "tf_id": source_id,
        "source_id": source_id,
        "restaurant_url": f"https://www.thefork.it/ristorante/da-mario-r{source_id}",
        "restaurant_name": name,
        "address": "Via Roma 1, Milano",
        "street": "Via Roma",
        "house_number": "1",
        "postal_code": "20100",
        "city": "Milano",
        "latitude": 45.0,
        "longitude": 9.0,
        "rating": 9.0,
        "review_count": 60,
        "low_review": False,
        "flags": [],
        "avg_price_eur": 35,
        "discount_pct": 20,
        "photo_count": 2,
        "opening_hours": {"mon": "19:00-23:00"},
        "reviews": [{"text": "Great"}],
        "cuisines": ["Mediterranean"],
        "dietary_options": ["Vegetarian"],
    }
    doc.update(overrides)
    return doc


def _candidate(
    google_id="g1",
    source="tripadvisor",
    source_id="ta1",
    candidate_id=None,
    score=0.91,
    label="MATCH",
    llm_label=None,
    **overrides,
):
    doc = {
        "_id": candidate_id or f"{google_id}:{source_id}",
        "google_id": google_id,
        "source": source,
        "source_id": source_id,
        "block_source": "geo",
        "fast_path": None,
        "score": score,
        "dmin": 0.58,
        "dmax": 0.63,
        "is_chain": False,
        "chain_brand": None,
        "chain_hardening": [],
        "components": {
            "name_sim": 0.92,
            "geo_dist_m": 18.0,
            "geo_score": 0.95,
            "street_sim": 0.9,
        },
        "label": label,
        "llm_label": llm_label,
    }
    doc.update(overrides)
    return doc


def test_select_links_uses_llm_label_as_final_decision():
    candidates = [_candidate(label="MATCH", llm_label="NON_MATCH")]

    assert select_links(candidates) == []


def test_select_links_prefers_llm_match_when_source_record_conflicts():
    candidates = [
        _candidate("g1", source_id="ta1", candidate_id="g1:ta1", score=0.99),
        _candidate(
            "g2",
            source_id="ta1",
            candidate_id="g2:ta1",
            score=0.60,
            label="UNCERTAIN",
            llm_label="MATCH",
        ),
    ]

    links = select_links(candidates, source="tripadvisor")

    assert len(links) == 1
    assert links[0]["google_id"] == "g2"
    assert links[0]["source_id"] == "ta1"
    assert links[0]["match_method"] == "llm"
    assert "source_record_matched_multiple_google" in links[0]["integration_flags"]
    assert "llm_override" in links[0]["integration_flags"]


def test_build_collections_writes_links_and_integrated_docs():
    db = _db()
    db.google.insert_one(_google())
    db.ta.insert_one(_ta())
    db.tf.insert_one(_tf())
    db.candidates.insert_many(
        [
            _candidate(source="tripadvisor", source_id="ta1"),
            _candidate(
                source="thefork",
                source_id="tf1",
                score=0.61,
                label="UNCERTAIN",
                llm_label="MATCH",
            ),
        ]
    )

    report = build_collections(
        db.google,
        db.ta,
        db.tf,
        db.candidates,
        db.links,
        db.integrated,
        _settings(batch_size=1),
        replace_destination=True,
        writer=_serial_replace,
    )

    assert report.links_selected == 2
    assert report.links_written == 2
    assert report.integrated_written == 1
    assert report.integrated_with_all_three == 1
    assert db.links.count_documents({}) == 2

    doc = db.integrated.find_one({"_id": "g1"})
    assert doc["has_google"] is True
    assert doc["has_tripadvisor"] is True
    assert doc["has_thefork"] is True
    assert doc["rating_platform_count"] == 3
    assert doc["rating_avg_5"] == 4.5
    assert doc["rating_range_5"] == 0.0
    assert doc["thefork_rating_raw_10"] == 9.0
    assert doc["thefork_rating_5"] == 4.5
    assert doc["match_provenance"]["tripadvisor"]["match_method"] == "deterministic_score"
    assert doc["match_provenance"]["thefork"]["match_method"] == "llm"
    assert "llm_override" in doc["integration_flags"]


def test_llm_non_match_excludes_candidate_from_integrated_dataset():
    db = _db()
    db.google.insert_one(_google())
    db.ta.insert_one(_ta())
    db.candidates.insert_one(_candidate(label="MATCH", llm_label="NON_MATCH"))

    report = build_collections(
        db.google,
        db.ta,
        db.tf,
        db.candidates,
        db.links,
        db.integrated,
        _settings(),
        replace_destination=True,
        writer=_serial_replace,
    )

    doc = db.integrated.find_one({"_id": "g1"})
    assert report.links_selected == 0
    assert db.links.count_documents({}) == 0
    assert doc["has_tripadvisor"] is False
    assert doc["match_status"] == "no_match"


def test_dry_run_does_not_write_to_mongo():
    db = _db()
    db.google.insert_one(_google())
    db.ta.insert_one(_ta())
    db.candidates.insert_one(_candidate())

    report = build_collections(
        db.google,
        db.ta,
        db.tf,
        db.candidates,
        db.links,
        db.integrated,
        _settings(),
        dry_run=True,
        writer=_serial_replace,
    )

    assert report.dry_run is True
    assert report.links_selected == 1
    assert report.integrated_with_tripadvisor == 1
    assert db.links.count_documents({}) == 0
    assert db.integrated.count_documents({}) == 0
