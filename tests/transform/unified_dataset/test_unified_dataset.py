import mongomock

from transform.unified_dataset.config import UnifiedSettings
from transform.unified_dataset.transform import (
    build_integrated_docs,
    select_links_for_source,
    serial_replace,
    unify_collections,
)


def _settings(**overrides):
    return UnifiedSettings(_env_file=None, **overrides)


def _db():
    return mongomock.MongoClient()["dataman"]


def _google(place_id="g1", name="Google One", rating=4.0, review_count=100):
    return {
        "_id": place_id,
        "place_id": place_id,
        "name": name,
        "address": "Via Roma 1, 20100 Milano",
        "street": "Via Roma",
        "house_number": "1",
        "postal_code": "20100",
        "city": "Milano",
        "latitude": 45.46,
        "longitude": 9.19,
        "rating": rating,
        "review_count": review_count,
        "is_dining": True,
        "is_operational": True,
        "category_tier": "restaurant",
        "flags": [],
        "website": "example.it",
        "phone": "+3902000000",
        "price_level": "PRICE_LEVEL_MODERATE",
        "reviews": [],
    }


def _ta(location_id="ta1", name="TA One", rating=4.5, total_review=80):
    return {
        "_id": f"https://tripadvisor.test/{location_id}",
        "source_url": f"https://tripadvisor.test/{location_id}",
        "ta_location_id": location_id,
        "restaurant_name": name,
        "address": "Via Roma 1, 20100 Milano",
        "street": "Via Roma",
        "house_number": "1",
        "postal_code": "20100",
        "city": "Milano",
        "latitude": 45.46,
        "longitude": 9.19,
        "has_coordinates": True,
        "rating": rating,
        "total_review": total_review,
        "website": "example.it",
        "phone": "+3902000000",
        "email": "info@example.it",
        "price_band": "€€",
        "price_tier_level": 2,
        "cuisines": ["Italiana"],
        "opening_hours": [],
        "reviews": [],
        "sample_size": 0,
        "flags": [],
    }


def _tf(tf_id="tf1", name="TF One", rating=8.0, review_count=50):
    return {
        "_id": f"slug-r{tf_id}",
        "source": "thefork",
        "source_id": f"slug-r{tf_id}",
        "tf_id": tf_id,
        "restaurant_url": f"https://thefork.test/{tf_id}",
        "restaurant_name": name,
        "address": "Via Roma, 1, 20100 Milano",
        "street": "Via Roma",
        "house_number": "1",
        "postal_code": "20100",
        "city": "Milano",
        "latitude": 45.46,
        "longitude": 9.19,
        "rating": rating,
        "review_count": review_count,
        "avg_price_eur": 35,
        "discount_pct": 20,
        "has_discount": True,
        "cuisines": ["Italiano"],
        "dietary_options": [],
        "opening_hours": [],
        "photo_count": 4,
        "review_snippets": [],
        "reviews": [],
        "sample_size": 0,
        "flags": [],
    }


def _candidate(
    candidate_id,
    google_id="g1",
    source="tripadvisor",
    source_id="ta1",
    label="MATCH",
    llm_label=None,
    score=0.9,
    fast_path=None,
    geo_dist_m=10.0,
    name_sim=0.9,
):
    return {
        "_id": candidate_id,
        "google_id": google_id,
        "source": source,
        "source_id": source_id,
        "label": label,
        "llm_label": llm_label,
        "score": score,
        "dmin": 0.5,
        "dmax": 0.8,
        "block_source": "geo",
        "fast_path": fast_path,
        "is_chain": False,
        "chain_brand": None,
        "chain_hardening": [],
        "components": {"geo_dist_m": geo_dist_m, "name_sim": name_sim},
    }


def test_effective_label_prefers_llm_label_over_automatic_label():
    links, report = select_links_for_source(
        [
            _candidate("auto_match_rejected", label="MATCH", llm_label="NON_MATCH"),
            _candidate(
                "llm_match_selected",
                source_id="ta2",
                label="UNCERTAIN",
                llm_label="MATCH",
                score=0.2,
            ),
        ],
        "tripadvisor",
    )

    assert report.match_candidates == 1
    assert links[0]["candidate_id"] == "llm_match_selected"
    assert links[0]["match_method"] == "llm"
    assert "llm_override" in links[0]["flags"]


def test_one_to_one_link_selection_and_conflict_flags():
    candidates = [
        _candidate("best", google_id="g1", source_id="ta1", score=0.95),
        _candidate("same_google", google_id="g1", source_id="ta2", score=0.90),
        _candidate("same_source", google_id="g2", source_id="ta1", score=0.80),
    ]

    links, report = select_links_for_source(candidates, "tripadvisor")

    assert len(links) == 1
    assert report.selected_links == 1
    assert links[0]["candidate_id"] == "best"
    assert "multiple_tripadvisor_matches" in links[0]["flags"]
    assert "source_record_matched_multiple_google" in links[0]["flags"]
    assert set(links[0]["rejected_candidate_ids"]) == {"same_google", "same_source"}


def test_tie_breaking_uses_llm_then_score_fast_path_distance_and_name():
    candidates = [
        _candidate("lower_score", source_id="ta1", score=0.8, fast_path="phone"),
        _candidate("higher_score", source_id="ta2", score=0.9),
        _candidate(
            "llm_wins",
            source_id="ta3",
            label="UNCERTAIN",
            llm_label="MATCH",
            score=0.1,
            geo_dist_m=100.0,
            name_sim=0.1,
        ),
    ]

    links, _ = select_links_for_source(candidates, "tripadvisor")

    assert links[0]["candidate_id"] == "llm_wins"


def test_builds_google_only_integrated_record():
    db = _db()
    db.google.insert_one(_google())

    docs, report = build_integrated_docs(db.google, db.ta, db.tf, [])

    assert report.written == 1
    assert docs[0]["_id"] == "google:g1"
    assert docs[0]["has_google"] is True
    assert docs[0]["has_tripadvisor"] is False
    assert docs[0]["has_thefork"] is False
    assert docs[0]["platform_count"] == 1
    assert docs[0]["sources"]["google"]["ids"]["place_id"] == "g1"


def test_builds_all_three_integrated_record_with_rating_metrics():
    db = _db()
    db.google.insert_one(_google(rating=4.0, review_count=100))
    db.ta.insert_one(_ta(rating=5.0, total_review=80))
    db.tf.insert_one(_tf(tf_id="tf1", rating=8.0, review_count=50))
    links = [
        {
            "_id": "tripadvisor:g1:ta1",
            "candidate_id": "g1:ta1",
            "google_id": "g1",
            "source": "tripadvisor",
            "source_id": "ta1",
            "effective_label": "MATCH",
            "label": "MATCH",
            "llm_label": None,
            "match_method": "automatic",
            "score": 0.9,
            "block_source": "geo",
            "fast_path": None,
            "components": {},
            "flags": [],
            "rejected_candidate_ids": [],
        },
        {
            "_id": "thefork:g1:tf1",
            "candidate_id": "g1:tf1",
            "google_id": "g1",
            "source": "thefork",
            "source_id": "tf1",
            "effective_label": "MATCH",
            "label": "MATCH",
            "llm_label": None,
            "match_method": "automatic",
            "score": 0.9,
            "block_source": "geo",
            "fast_path": None,
            "components": {},
            "flags": ["multiple_thefork_matches"],
            "rejected_candidate_ids": ["other"],
        },
    ]

    docs, report = build_integrated_docs(db.google, db.ta, db.tf, links)
    doc = docs[0]

    assert report.with_tripadvisor == 1
    assert report.with_thefork == 1
    assert report.with_all_three == 1
    assert doc["has_all_three_platforms"] is True
    assert doc["platform_count"] == 3
    assert doc["thefork_rating_raw_10"] == 8.0
    assert doc["thefork_rating_5"] == 4.0
    assert doc["rating_platform_count"] == 3
    assert doc["rating_avg_5"] == 4.333
    assert doc["rating_range_5"] == 1.0
    assert doc["tripadvisor_review_count"] == 80
    assert doc["thefork_review_count"] == 50
    # Canonical cuisine reconciles Tripadvisor "Italiana" + TheFork "Italiano" into one bucket.
    assert doc["cuisine_tags"] == ["Italian"]
    assert doc["cuisine_primary"] == "Italian"
    assert doc["cuisine_primary_source"] == "tripadvisor"
    assert doc["cuisine_n_sources"] == 2
    assert doc["cuisine_agreement"] == "agree"
    assert doc["website"] == "example.it"
    assert doc["website_source"] == "google_tripadvisor"
    assert doc["website_match_status"] == "exact_match"
    assert doc["phone_match_status"] == "exact_match"
    assert doc["phones"] == ["+3902000000"]
    assert doc["price_level"] == "MODERATE"
    assert doc["price_level_source"] == "majority"
    assert "price_level_raw" not in doc
    assert "multiple_thefork_matches" in doc["integration_flags"]
    assert doc["sources"]["tripadvisor"]["contacts"]["email"] == "info@example.it"
    assert doc["sources"]["thefork"]["price"]["avg_price_eur"] == 35


def test_top_level_website_host_match_and_phone_conflict():
    db = _db()
    google = _google()
    google["website"] = "pizza.it/home"
    google["phone"] = "+3902111111"
    db.google.insert_one(google)
    ta = _ta()
    ta["website"] = "pizza.it"
    ta["phone"] = "+3902222222"
    db.ta.insert_one(ta)
    links = [
        {
            "_id": "tripadvisor:g1:ta1",
            "candidate_id": "g1:ta1",
            "google_id": "g1",
            "source": "tripadvisor",
            "source_id": "ta1",
            "effective_label": "MATCH",
            "label": "MATCH",
            "llm_label": None,
            "match_method": "automatic",
            "score": 0.9,
            "block_source": "geo",
            "fast_path": None,
            "components": {},
            "flags": [],
            "rejected_candidate_ids": [],
        }
    ]

    docs, _ = build_integrated_docs(db.google, db.ta, db.tf, links)
    doc = docs[0]

    assert doc["website"] == "pizza.it"
    assert doc["website_source"] == "google_tripadvisor"
    assert doc["website_match_status"] == "host_match"
    assert doc["website_evidence"] == [
        {"source": "google", "value": "pizza.it/home"},
        {"source": "tripadvisor", "value": "pizza.it"},
    ]
    assert doc["phone_match_status"] == "conflict"
    assert doc["phones"] == ["+3902111111", "+3902222222"]


def test_top_level_price_falls_back_to_tripadvisor_then_thefork():
    db = _db()
    google = _google()
    google["price_level"] = None
    db.google.insert_one(google)
    db.ta.insert_one(_ta())
    db.tf.insert_one(_tf(tf_id="tf1", rating=8.0, review_count=50))
    links = [
        {
            "_id": "tripadvisor:g1:ta1",
            "candidate_id": "g1:ta1",
            "google_id": "g1",
            "source": "tripadvisor",
            "source_id": "ta1",
            "effective_label": "MATCH",
            "label": "MATCH",
            "llm_label": None,
            "match_method": "automatic",
            "score": 0.9,
            "block_source": "geo",
            "fast_path": None,
            "components": {},
            "flags": [],
            "rejected_candidate_ids": [],
        }
    ]

    docs, _ = build_integrated_docs(db.google, db.ta, db.tf, links)
    assert docs[0]["price_level"] == "MODERATE"
    assert docs[0]["price_level_source"] == "tripadvisor"
    assert "price_level_raw" not in docs[0]

    db.ta.delete_many({})
    docs, _ = build_integrated_docs(
        db.google,
        db.ta,
        db.tf,
        [
            {
                "_id": "thefork:g1:tf1",
                "candidate_id": "g1:tf1",
                "google_id": "g1",
                "source": "thefork",
                "source_id": "tf1",
                "effective_label": "MATCH",
                "label": "MATCH",
                "llm_label": None,
                "match_method": "automatic",
                "score": 0.9,
                "block_source": "geo",
                "fast_path": None,
                "components": {},
                "flags": [],
                "rejected_candidate_ids": [],
            }
        ],
    )
    assert docs[0]["price_level"] == "MODERATE"
    assert docs[0]["price_level_source"] == "thefork"
    assert "price_level_raw" not in docs[0]


def test_unify_replace_destination_replaces_outputs_and_is_idempotent():
    db = _db()
    db.google.insert_many([_google("g1"), _google("g2", name="Google Two")])
    db.ta.insert_one(_ta("ta1"))
    db.tf.insert_one(_tf("tf1"))
    db.candidates.insert_many(
        [
            _candidate("g1:ta1", source="tripadvisor", source_id="ta1"),
            _candidate("g1:tf1", source="thefork", source_id="tf1"),
        ]
    )
    db.links.insert_one({"_id": "stale_link", "source": "tripadvisor"})
    db.integrated.insert_one({"_id": "stale_integrated"})

    first = unify_collections(
        db.google,
        db.ta,
        db.tf,
        db.candidates,
        db.links,
        db.integrated,
        _settings(),
        replace_destination=True,
        writer=serial_replace,
    )
    second = unify_collections(
        db.google,
        db.ta,
        db.tf,
        db.candidates,
        db.links,
        db.integrated,
        _settings(),
        replace_destination=False,
        writer=serial_replace,
    )

    assert db.links.find_one({"_id": "stale_link"}) is None
    assert db.integrated.find_one({"_id": "stale_integrated"}) is None
    assert db.links.count_documents({}) == 2
    assert db.integrated.count_documents({}) == 2
    assert db.integrated.find_one({"_id": "google:g1"})["has_all_three_platforms"] is True
    assert first.integrated.written == second.integrated.written == 2


def test_skip_links_reuses_existing_links_for_integrated_rebuild():
    db = _db()
    db.google.insert_one(_google("g1"))
    db.ta.insert_one(_ta("ta1"))
    db.links.insert_one(
        {
            "_id": "tripadvisor:g1:ta1",
            "candidate_id": "g1:ta1",
            "google_id": "g1",
            "source": "tripadvisor",
            "source_id": "ta1",
            "effective_label": "MATCH",
            "label": "MATCH",
            "llm_label": None,
            "match_method": "automatic",
            "score": 0.9,
            "block_source": "geo",
            "fast_path": None,
            "components": {},
            "flags": [],
            "rejected_candidate_ids": [],
        }
    )

    report = unify_collections(
        db.google,
        db.ta,
        db.tf,
        db.candidates,
        db.links,
        db.integrated,
        _settings(),
        skip_links=True,
        writer=serial_replace,
    )

    assert report.skip_links is True
    assert report.links == []
    assert db.integrated.find_one({"_id": "google:g1"})["has_tripadvisor"] is True
