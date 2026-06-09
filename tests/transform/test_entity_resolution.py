import csv

import mongomock

from transform.entity_resolution.blocking import geo_block, postal_name_block
from transform.entity_resolution.calibrate import (
    analyze_calibration_rows,
    write_calibration_csv,
)
from transform.entity_resolution.chains import chain_brand_for_name
from transform.entity_resolution.config import ERSettings
from transform.entity_resolution.preprocess import normalize_name
from transform.entity_resolution.scoring import label, score_components
from transform.entity_resolution.transform import resolve_collections, serial_upsert


def _settings(**overrides):
    return ERSettings(_env_file=None, **overrides)


def _google(place_id="g1", name="Da Mario", lat=45.0, lon=9.0, **overrides):
    doc = {
        "_id": place_id,
        "place_id": place_id,
        "name": name,
        "latitude": lat,
        "longitude": lon,
        "street": "Via Roma",
        "house_number": "1",
        "postal_code": "20100",
        "phone": None,
        "website": None,
        "is_dining": True,
        "is_operational": True,
        "cuisines": ["Italiano"],
    }
    doc.update(overrides)
    return doc


def _ta(ta_id="ta1", name="Da Mario", lat=None, lon=None, has_coordinates=False, **overrides):
    doc = {
        "_id": f"https://www.tripadvisor.it/Restaurant_Review-d{ta_id}.html",
        "ta_location_id": ta_id,
        "restaurant_name": name,
        "latitude": lat,
        "longitude": lon,
        "has_coordinates": has_coordinates,
        "street": "Via Roma",
        "house_number": "1",
        "postal_code": "20100",
        "phone": None,
        "website": None,
        "cuisines": ["Italiano"],
    }
    doc.update(overrides)
    return doc


def _tf(tf_id="tf1", name="Da Mario", lat=45.0, lon=9.0, **overrides):
    doc = {
        "_id": f"da-mario-r{tf_id}",
        "tf_id": tf_id,
        "restaurant_name": name,
        "latitude": lat,
        "longitude": lon,
        "street": "Via Roma",
        "house_number": "1",
        "postal_code": "20100",
        "cuisines": ["Italiano"],
    }
    doc.update(overrides)
    return doc


def _db():
    return mongomock.MongoClient()["dataman"]


def test_normalize_name_expands_strips_and_collapses():
    assert normalize_name("  RIST.   DA, MARIO!!  P.ZA   TEST ") == (
        "ristorante da mario piazza test"
    )


def test_geo_block_respects_radius_and_excludes_null_coords():
    google = [_google()]
    near = _tf("near", lat=45.0009, lon=9.0)
    far = _tf("far", lat=45.0018, lon=9.0)
    null_coords = _tf("null", lat=None, lon=None)

    pairs = geo_block(google, [near, far, null_coords], radius_m=150.0)

    assert [pair.source["tf_id"] for pair in pairs] == ["near"]


def test_postal_name_block_requires_cap_and_shared_long_token():
    google = [_google(name="Da Mario", postal_code="20100")]
    shared_token = _ta("same", name="Mario Bistrot", postal_code="20100")
    no_shared_long_token = _ta("short", name="Bar X", postal_code="20100")
    different_cap = _ta("cap", name="Mario Bistrot", postal_code="20199")

    pairs = postal_name_block(google, [shared_token, no_shared_long_token, different_cap])

    assert [pair.source["ta_location_id"] for pair in pairs] == ["same"]


def test_fast_path_phone_writes_match_without_composite_score():
    db = _db()
    db.google.insert_one(_google(name="Fast Mario", postal_code="20100", phone="+39021234567"))
    db.ta.insert_one(
        _ta(
            "ta1",
            name="Fast Mario",
            postal_code="20100",
            phone="+39021234567",
            has_coordinates=False,
            latitude=None,
            longitude=None,
        )
    )

    report = resolve_collections(
        db.google,
        db.ta,
        db.tf,
        db.dest,
        _settings(dmax_tripadvisor=0.55),
        source="tripadvisor",
        writer=serial_upsert,
    )

    doc = db.dest.find_one({"_id": "g1:ta1"})
    assert doc["label"] == "MATCH"
    assert doc["block_source"] == "fast_path"
    assert doc["fast_path"] == "phone"
    assert doc["score"] == 1.0
    assert report.sources[0].block_counts["fast_path"] == 1


def test_block_source_values_are_written():
    db = _db()
    db.google.insert_many(
        [
            _google("g_geo", name="Geo Place", lat=45.0, lon=9.0, postal_code="20100"),
            _google("g_postal", name="Postal Mario", postal_code="20101"),
            _google(
                "g_fast",
                name="Fast Luigi",
                postal_code="20102",
                phone="+39027654321",
            ),
        ]
    )
    db.tf.insert_one(_tf("tf_geo", name="Geo Place", lat=45.0005, lon=9.0))
    db.ta.insert_many(
        [
            _ta("ta_postal", name="Postal Mario", postal_code="20101"),
            _ta(
                "ta_fast",
                name="Fast Luigi",
                postal_code="20102",
                phone="+39027654321",
            ),
            _ta("ta_unblockable", name="Only Name", postal_code=None),
        ]
    )

    resolve_collections(
        db.google,
        db.ta,
        db.tf,
        db.dest,
        _settings(),
        source="all",
        writer=serial_upsert,
    )

    assert {doc["block_source"] for doc in db.dest.find()} == {
        "geo",
        "postal_code",
        "fast_path",
        "unblockable",
    }


def test_weight_regimes_include_ta_contacts_and_exclude_tf_contacts():
    components = {
        "name_sim": 0.0,
        "geo_score": 0.0,
        "street_sim": 0.0,
        "phone_match": 1.0,
        "website_match": 1.0,
    }

    assert score_components(components, "tripadvisor") == 0.25
    assert score_components(components, "thefork") == 0.0


def test_label_threshold_boundaries():
    assert label(0.85, dmin=0.40, dmax=0.85) == "MATCH"
    assert label(0.40, dmin=0.40, dmax=0.85) == "NON_MATCH"
    assert label(0.60, dmin=0.40, dmax=0.85) == "UNCERTAIN"


def test_chain_brand_detection_uses_curated_names_only():
    assert chain_brand_for_name("McDonald's") == "mcdonald s"
    assert chain_brand_for_name("La Piadineria Duomo") == "la piadineria"
    assert chain_brand_for_name("Old Wild West Milano") == "old wild west"
    assert chain_brand_for_name("Bar Centrale") is None
    assert chain_brand_for_name("Pizzeria") is None


def test_source_specific_thresholds_fallback_to_global_defaults():
    settings = _settings(dmin=0.42, dmax=0.84)

    assert settings.thresholds_for_source("tripadvisor") == (0.42, 0.84)
    assert settings.thresholds_for_source("thefork") == (0.42, 0.84)
    assert settings.thresholds_for_source("tripadvisor", is_chain=True) == (0.42, 0.84)


def test_chain_thresholds_fallback_to_source_then_override():
    source_settings = _settings(
        dmin=0.40,
        dmax=0.85,
        dmin_tripadvisor=0.57,
        dmax_tripadvisor=0.62,
    )
    chain_settings = _settings(
        dmin=0.40,
        dmax=0.85,
        dmin_tripadvisor=0.57,
        dmax_tripadvisor=0.62,
        dmin_chain_tripadvisor=0.70,
        dmax_chain_tripadvisor=0.90,
    )

    assert source_settings.thresholds_for_source("tripadvisor", is_chain=True) == (
        0.57,
        0.62,
    )
    assert chain_settings.thresholds_for_source("tripadvisor", is_chain=True) == (
        0.70,
        0.90,
    )


def test_source_specific_thresholds_drive_candidate_labels():
    db = _db()
    db.google.insert_one(_google(name="Strict TF", lat=45.0, lon=9.0))
    db.tf.insert_one(_tf("tf1", name="Strict TF", lat=45.0, lon=9.0, street=None))

    report = resolve_collections(
        db.google,
        db.ta,
        db.tf,
        db.dest,
        _settings(dmin=0.40, dmax=0.85, dmin_thefork=0.68, dmax_thefork=0.86),
        source="thefork",
        writer=serial_upsert,
    )

    doc = db.dest.find_one({"_id": "g1:tf1"})
    assert doc["score"] == 0.85
    assert doc["label"] == "UNCERTAIN"
    assert report.source_thresholds["thefork"] == {"dmin": 0.68, "dmax": 0.86}
    assert report.sources[0].dmin == 0.68
    assert report.sources[0].dmax == 0.86


def test_chain_geo_match_requires_stricter_distance():
    db = _db()
    db.google.insert_one(_google(name="La Piadineria", lat=45.0, lon=9.0))
    db.tf.insert_one(_tf("tf1", name="La Piadineria", lat=45.0009, lon=9.0))

    resolve_collections(
        db.google,
        db.ta,
        db.tf,
        db.dest,
        _settings(
            dmin=0.40,
            dmax=0.85,
            dmin_chain_thefork=0.70,
            dmax_chain_thefork=0.90,
            chain_auto_match_radius_m=75.0,
        ),
        source="thefork",
        writer=serial_upsert,
    )

    doc = db.dest.find_one({"_id": "g1:tf1"})
    assert doc["is_chain"] is True
    assert doc["chain_brand"] == "la piadineria"
    assert doc["dmin"] == 0.70
    assert doc["dmax"] == 0.90
    assert doc["score"] > 0.90
    assert doc["label"] == "UNCERTAIN"
    assert "chain_distance_gt_auto_match_radius" in doc["chain_hardening"]


def test_chain_phone_fast_path_still_matches_without_geo():
    db = _db()
    db.google.insert_one(_google(name="McDonald's", postal_code="20100", phone="+39021234567"))
    db.ta.insert_one(
        _ta(
            "ta1",
            name="McDonald's",
            postal_code="20100",
            phone="+39021234567",
            has_coordinates=False,
            latitude=None,
            longitude=None,
        )
    )

    resolve_collections(
        db.google,
        db.ta,
        db.tf,
        db.dest,
        _settings(dmax_tripadvisor=0.80, dmax_chain_tripadvisor=0.55),
        source="tripadvisor",
        writer=serial_upsert,
    )

    doc = db.dest.find_one({"_id": "g1:ta1"})
    assert doc["is_chain"] is True
    assert doc["block_source"] == "fast_path"
    assert doc["fast_path"] == "phone"
    assert doc["label"] == "MATCH"


def test_chain_website_fast_path_is_suppressed_without_geo():
    db = _db()
    db.google.insert_one(
        _google(name="La Piadineria", postal_code="20100", website="lapiadineria.com")
    )
    db.ta.insert_one(
        _ta(
            "ta1",
            name="La Piadineria",
            postal_code="20100",
            website="lapiadineria.com",
            has_coordinates=False,
            latitude=None,
            longitude=None,
        )
    )

    resolve_collections(
        db.google,
        db.ta,
        db.tf,
        db.dest,
        _settings(),
        source="tripadvisor",
        writer=serial_upsert,
    )

    doc = db.dest.find_one({"_id": "g1:ta1"})
    assert doc["is_chain"] is True
    assert doc["block_source"] == "postal_code"
    assert doc["fast_path"] is None
    assert doc["label"] == "UNCERTAIN"
    assert "chain_website_fast_path_suppressed" in doc["chain_hardening"]
    assert "chain_no_geo_evidence" in doc["chain_hardening"]


def test_upsert_does_not_overwrite_non_null_llm_label():
    db = _db()
    db.google.insert_one(_google(name="Protected", lat=45.0, lon=9.0))
    db.tf.insert_one(_tf("tf1", name="Protected", lat=45.0005, lon=9.0))
    db.dest.insert_one({"_id": "g1:tf1", "score": 0.12, "llm_label": "MATCH"})

    report = resolve_collections(
        db.google,
        db.ta,
        db.tf,
        db.dest,
        _settings(),
        source="thefork",
        writer=serial_upsert,
    )

    doc = db.dest.find_one({"_id": "g1:tf1"})
    assert doc["score"] == 0.12
    assert doc["llm_label"] == "MATCH"
    assert report.sources[0].skipped_protected == 1


def test_replace_destination_deletes_selected_source_before_writing():
    db = _db()
    db.google.insert_one(_google(name="Replace TF", lat=45.0, lon=9.0))
    db.tf.insert_one(_tf("tf1", name="Replace TF", lat=45.0005, lon=9.0))
    db.dest.insert_many(
        [
            {"_id": "stale_tf", "source": "thefork", "llm_label": "MATCH"},
            {"_id": "keep_ta", "source": "tripadvisor", "llm_label": "MATCH"},
        ]
    )

    report = resolve_collections(
        db.google,
        db.ta,
        db.tf,
        db.dest,
        _settings(),
        source="thefork",
        replace_destination=True,
        writer=serial_upsert,
    )

    assert db.dest.find_one({"_id": "stale_tf"}) is None
    assert db.dest.find_one({"_id": "keep_ta"}) is not None
    assert db.dest.find_one({"_id": "g1:tf1"}) is not None
    assert report.replace_destination is True
    assert report.sources[0].deleted_existing == 1
    assert report.sources[0].inserted == 1


def test_source_thefork_produces_no_ta_candidates():
    db = _db()
    db.google.insert_one(_google(name="Da Mario", postal_code="20100"))
    db.ta.insert_one(_ta("ta1", name="Da Mario", postal_code="20100"))
    db.tf.insert_one(_tf("tf1", name="Da Mario", lat=45.0005, lon=9.0))

    report = resolve_collections(
        db.google,
        db.ta,
        db.tf,
        db.dest,
        _settings(),
        source="thefork",
        writer=serial_upsert,
    )

    assert [source_report.source for source_report in report.sources] == ["thefork"]
    assert db.dest.count_documents({"source": "tripadvisor"}) == 0
    assert db.dest.count_documents({"source": "thefork"}) == 1


def test_calibration_export_writes_joined_labelable_csv(tmp_path):
    db = _db()
    db.google.insert_one(_google(name="Export Google"))
    db.tf.insert_one(_tf("tf1", name="Export TF"))
    db.candidates.insert_one(
        {
            "_id": "g1:tf1",
            "google_id": "g1",
            "source": "thefork",
            "source_id": "tf1",
            "score": 0.91,
            "dmin": 0.68,
            "dmax": 0.90,
            "is_chain": True,
            "chain_brand": "la piadineria",
            "chain_hardening": ["chain_distance_gt_auto_match_radius"],
            "label": "MATCH",
            "block_source": "geo",
            "fast_path": None,
            "components": {"name_sim": 0.8, "geo_score": 0.9},
        }
    )
    output = tmp_path / "calibration.csv"

    written = write_calibration_csv(
        db.google,
        db.ta,
        db.tf,
        db.candidates,
        output,
        sample_size=10,
        chain_filter="chain",
    )

    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    assert written == 1
    assert rows[0]["is_chain"] == "True"
    assert rows[0]["chain_brand"] == "la piadineria"
    assert rows[0]["dmin"] == "0.68"
    assert rows[0]["dmax"] == "0.9"
    assert rows[0]["google_name"] == "Export Google"
    assert rows[0]["source_name"] == "Export TF"
    assert rows[0]["human_label"] == ""


def test_calibration_analyze_reports_suggestions():
    report = analyze_calibration_rows(
        [
            {"source": "tripadvisor", "score": "0.95", "human_label": "MATCH"},
            {"source": "tripadvisor", "score": "0.70", "human_label": "MATCH"},
            {"source": "tripadvisor", "score": "0.20", "human_label": "NON_MATCH"},
            {
                "source": "thefork",
                "score": "0.96",
                "is_chain": "true",
                "human_label": "MATCH",
            },
            {
                "source": "thefork",
                "score": "0.25",
                "is_chain": "true",
                "human_label": "NON_MATCH",
            },
            {"source": "thefork", "score": "0.55", "human_label": ""},
        ]
    )

    assert report["labeled_rows"] == 5
    assert report["human_counts"] == {"MATCH": 3, "NON_MATCH": 2}
    assert report["suggestions"]
    assert report["source_suggestions"]["tripadvisor"]["labeled_rows"] == 3
    assert report["recommended_source_thresholds"]["tripadvisor"]["dmin"] is not None
    assert report["recommended_source_thresholds"]["thefork"]["dmax"] is not None
    assert report["chain_suggestions"]["chain"]["labeled_rows"] == 2
    assert report["recommended_chain_source_thresholds"]["thefork"]["dmin"] is not None
    assert (
        "--dmin-chain-thefork" in report["recommended_chain_source_thresholds"]["example_command"]
    )
    assert "--dmin-tripadvisor" in report["recommended_source_thresholds"]["example_command"]
    assert "--dmax-thefork" in report["recommended_source_thresholds"]["example_command"]
