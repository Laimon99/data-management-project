from integration_assessment.link_metrics import compute_link_metrics


def test_link_metrics_detects_true_match_dropped_by_one_to_one_selection():
    gold = [
        {
            "_id": "c1",
            "source": "tripadvisor",
            "google_id": "g1",
            "source_id": "ta1",
            "human_label": "MATCH",
            "score": "0.95",
        },
        {
            "_id": "c2",
            "source": "tripadvisor",
            "google_id": "g2",
            "source_id": "ta2",
            "human_label": "MATCH",
            "score": "0.9",
        },
    ]
    candidates = [
        {"_id": "c1", "label": "MATCH", "score": 0.95},
        {"_id": "c2", "label": "MATCH", "score": 0.9},
    ]
    links = [
        {
            "_id": "tripadvisor:g1:ta1",
            "source": "tripadvisor",
            "google_id": "g1",
            "source_id": "ta1",
            "effective_label": "MATCH",
        }
    ]
    integrated = [
        {
            "_id": "google:g1",
            "sources": {
                "tripadvisor": {
                    "ids": {
                        "ta_location_id": "ta1",
                        "source_url": "https://tripadvisor.test/ta1",
                    }
                }
            },
        }
    ]

    metrics = compute_link_metrics(gold, candidates, links, integrated)

    assert metrics["total_true_matches"] == 2
    assert metrics["linked_true_matches"] == 1
    assert metrics["integrated_true_matches"] == 1
    assert metrics["dropped_by_1to1_selection"] == 1
    assert metrics["errors"][0]["issue_type"] == "dropped_by_1to1_selection"
