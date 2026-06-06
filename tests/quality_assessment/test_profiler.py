import csv
import json

from quality_assessment.profiler import (
    ANOMALY_FIELDNAMES,
    analyze_source,
    tripadvisor_config,
    write_csv,
)


def test_tripadvisor_profile_flags_missing_and_sparse_records(tmp_path) -> None:
    dataset = [
        {
            "source_url": "https://example.test/a",
            "restaurant_name": "A",
            "address": "Via A, Milano",
            "rating": "4,3",
            "total_review": "(18 recensioni)",
        },
        {
            "source_url": "https://example.test/b",
            "restaurant_name": "B",
            "address": "NaN",
            "rating": "8,0",
            "total_review": "(0 recensioni)",
        },
    ]
    path = tmp_path / "tripadvisor.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    result = analyze_source(tripadvisor_config(path), low_review_threshold=20)

    assert result["record_count"] == 2
    assert result["summary"]["valid_rating_count"] == 1
    assert result["summary"]["low_review_records"] == 1
    assert result["summary"]["zero_review_records"] == 1
    assert result["summary"]["timestamp_coverage_pct"] == 0.0
    assert result["summary"]["collection_duration_hours"] == 27.0
    assert result["summary"]["timeliness_score_pct"] == 43.75
    assert result["summary"]["anomaly_count"] == len(result["anomalies"])
    assert result["summary"]["overall_quality_score_pct"] > 0
    issue_types = {item["issue_type"] for item in result["anomalies"]}
    assert "missing_critical_field" in issue_types
    assert "invalid_rating" in issue_types
    assert "low_review_count" in issue_types
    assert "zero_reviews" in issue_types


def test_tripadvisor_validity_checks_source_specific_field_formats(tmp_path) -> None:
    dataset = [
        {
            "source_url": "not-a-url",
            "restaurant_name": "A",
            "address": "Via A, Milano",
            "rating": "4,0",
            "total_review": "(25 recensioni)",
            "price_range": "expensive",
            "number_photo_uploaded": "many",
            "website": "example.test",
            "phone_number": "abc",
            "email": "bad-email",
        },
    ]
    path = tmp_path / "tripadvisor.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    result = analyze_source(tripadvisor_config(path), low_review_threshold=20)

    invalid_format_fields = {
        item["field"]
        for item in result["anomalies"]
        if item["issue_type"] == "invalid_field_format"
    }
    assert result["summary"]["validity_score_pct"] < 100.0
    assert invalid_format_fields == {
        "source_url",
        "price_range",
        "photo_count",
        "website",
        "phone_number",
        "email",
    }


def test_profile_flags_unparseable_and_negative_review_counts(tmp_path) -> None:
    dataset = [
        {
            "source_url": "https://example.test/a",
            "restaurant_name": "A",
            "address": "Via A, Milano",
            "rating": "not-a-rating",
            "total_review": "-5 reviews",
        },
        {
            "source_url": "https://example.test/b",
            "restaurant_name": "B",
            "address": "Via B, Milano",
            "rating": "4,0",
            "total_review": "not-a-count",
        },
    ]
    path = tmp_path / "tripadvisor.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    result = analyze_source(tripadvisor_config(path), low_review_threshold=20)

    issue_types = {item["issue_type"] for item in result["anomalies"]}
    assert "unparseable_rating" in issue_types
    assert "invalid_review_count" in issue_types
    assert "unparseable_review_count" in issue_types
    assert result["summary"]["valid_review_count"] == 0


def test_write_csv_preserves_header_for_empty_anomalies(tmp_path) -> None:
    path = tmp_path / "anomalies.csv"

    write_csv(path, [], ANOMALY_FIELDNAMES)

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        assert next(reader) == ANOMALY_FIELDNAMES
