from integration_assessment.geo_metrics import compute_geo_metrics


def test_geo_metrics_distance_buckets_and_coordinate_coverage():
    gold = [
        {
            "_id": "c1",
            "source": "tripadvisor",
            "google_id": "g1",
            "source_id": "ta1",
            "human_label": "MATCH",
        }
    ]
    candidates = [
        {
            "_id": "c1",
            "source": "tripadvisor",
            "label": "MATCH",
            "components": {"geo_dist_m": 0.0},
        },
        {"_id": "unblockable", "source": "tripadvisor", "label": "UNBLOCKABLE"},
    ]
    links = [
        {
            "source": "tripadvisor",
            "google_id": "g1",
            "source_id": "ta1",
            "components": {"geo_dist_m": 0.0},
        }
    ]
    google = [{"_id": "g1", "place_id": "g1", "latitude": 45.0, "longitude": 9.0}]
    tripadvisor = [
        {"_id": "ta1", "ta_location_id": "ta1", "latitude": 45.0, "longitude": 9.0},
        {"_id": "ta2", "ta_location_id": "ta2"},
    ]

    metrics = compute_geo_metrics(gold, candidates, links, google, tripadvisor)
    summary = metrics["summary"]

    assert summary["distance_rows"] == 1
    assert summary["median_m"] == 0.0
    assert summary["within_50m_pct"] == 1.0
    assert summary["tripadvisor_coordinate_coverage_pct"] == 0.5
    assert summary["tripadvisor_without_coordinates"] == 1
    assert summary["tripadvisor_unblockable_candidates"] == 1
