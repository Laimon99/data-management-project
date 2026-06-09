from integration_assessment.assessment import build_payload
from integration_assessment.config import IntegrationAssessmentSettings


def _row(candidate_id, human_label, score):
    return {
        "_id": candidate_id,
        "source": "tripadvisor",
        "google_id": f"g-{candidate_id}",
        "source_id": f"ta-{candidate_id}",
        "score": str(score),
        "is_chain": "False",
        "human_label": human_label,
    }


def _candidate(candidate_id, label, score):
    return {
        "_id": candidate_id,
        "source": "tripadvisor",
        "google_id": f"g-{candidate_id}",
        "source_id": f"ta-{candidate_id}",
        "label": label,
        "score": score,
        "dmin": 0.4,
        "dmax": 0.8,
        "is_chain": False,
    }


def test_payload_separates_out_of_sample_and_in_calibration_gold_rows():
    payload = build_payload(
        settings=IntegrationAssessmentSettings(_env_file=None),
        gold_rows=[_row("holdout", "MATCH", 0.95)],
        in_calibration_gold_rows=[_row(f"cal-m-{index}", "MATCH", 0.95) for index in range(3)]
        + [_row(f"cal-n-{index}", "NON_MATCH", 0.1) for index in range(3)],
        evaluation_rows_after_csv_dedupe=2,
        excluded_evaluation_overlap=1,
        candidates=[
            _candidate("holdout", "MATCH", 0.95),
            *[_candidate(f"cal-m-{index}", "MATCH", 0.95) for index in range(3)],
            *[_candidate(f"cal-n-{index}", "NON_MATCH", 0.1) for index in range(3)],
        ],
        links=[],
        integrated_docs=[],
        google_docs=[],
        tripadvisor_docs=[],
    )

    assert payload["gold"]["evaluation"]["rows"] == 1
    assert payload["gold"]["evaluation"]["rows_after_csv_dedupe"] == 2
    assert payload["gold"]["in_calibration"]["rows"] == 6
    assert payload["gold"]["evaluation"]["excluded_overlap_with_in_calibration"] == 1
    assert payload["er"]["gold_rows"] == 1
    assert payload["er"]["cross_validation_gold_rows"] == 6
    assert payload["er"]["in_sample"]["summaries"]["overall:all"]["match_precision"] == 1.0
    assert payload["link_survival_in_calibration"]["total_true_matches"] == 3
