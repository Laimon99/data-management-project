"""Unit tests for the read-only analysis helpers.

These exercise the pure logic only — no live ClickHouse connection — consistent
with the project's preference for source-level tests.
"""

from __future__ import annotations

import pytest

from analysis import queries
from analysis.constants import (
    CENTER_RADIUS_KM,
    DUOMO_LAT,
    DUOMO_LON,
    POPULAR_NEIGHBOURHOODS,
)
from analysis.geo import (
    assign_neighbourhood,
    classify_center_periphery,
    distance_to_duomo_km,
    is_sparse,
)

# A point well outside Milan, used as the "far" / periphery case.
FAR_LAT, FAR_LON = 45.0, 9.0


# --- distance / center-periphery ------------------------------------------


def test_distance_to_duomo_is_zero_at_duomo():
    assert distance_to_duomo_km(DUOMO_LAT, DUOMO_LON) == pytest.approx(0.0, abs=1e-6)


def test_distance_to_duomo_positive_for_offset_point():
    # ~0.01 deg lat north of the Duomo ~= 1.1 km.
    distance = distance_to_duomo_km(DUOMO_LAT + 0.01, DUOMO_LON)
    assert 1.0 < distance < 1.3


def test_classify_center_for_near_point():
    assert classify_center_periphery(DUOMO_LAT, DUOMO_LON) == "center"


def test_classify_periphery_for_far_point():
    assert classify_center_periphery(FAR_LAT, FAR_LON) == "periphery"


def test_classify_respects_radius_boundary():
    # A point just inside 2 km is center; bumping it past the radius flips it.
    near = (DUOMO_LAT + 0.01, DUOMO_LON)  # ~1.1 km
    assert classify_center_periphery(*near, radius_km=CENTER_RADIUS_KM) == "center"
    assert classify_center_periphery(*near, radius_km=0.5) == "periphery"


# --- null / invalid coordinate handling -----------------------------------


@pytest.mark.parametrize("lat,lon", [(None, 9.19), (45.46, None), (None, None), (0.0, 0.0)])
def test_invalid_coordinates_excluded_not_zeroed(lat, lon):
    assert distance_to_duomo_km(lat, lon) is None
    assert classify_center_periphery(lat, lon) is None
    assert assign_neighbourhood(lat, lon) is None


# --- neighbourhood assignment ---------------------------------------------


def test_assign_neighbourhood_inside_navigli():
    navigli = next(h for h in POPULAR_NEIGHBOURHOODS if h.name == "navigli")
    assert assign_neighbourhood(navigli.lat, navigli.lon) == "navigli"


def test_assign_neighbourhood_far_point_is_other():
    assert assign_neighbourhood(FAR_LAT, FAR_LON) == "other"


def test_popular_neighbourhoods_collapsed_to_named_quartieri():
    names = {h.name for h in POPULAR_NEIGHBOURHOODS}
    assert {"duomo", "navigli", "brera", "porta_venezia", "sempione"} <= names
    # Suffix anchors (navigli_1/2/3) were collapsed away.
    assert not any(name[-1].isdigit() for name in names)


# --- sparse classifier ----------------------------------------------------


@pytest.mark.parametrize(
    "count,expected",
    [(0, True), (19, True), (20, False), (21, False), (1000, False)],
)
def test_is_sparse_boundary(count, expected):
    assert is_sparse(count) is expected


def test_is_sparse_null_not_treated_as_zero():
    # A missing review count is unknown, not sparse — it must not inflate the
    # sparse bucket.
    assert is_sparse(None) is False


# --- query construction ----------------------------------------------------


@pytest.mark.parametrize(
    "builder",
    [
        queries.q1_summary,
        queries.q1_histogram,
        queries.q1_tolerance_bands,
        queries.q3_correlations,
        queries.q3_binned,
        queries.q5_platform_rows,
        queries.q6_popularity_bins,
    ],
)
def test_consistency_queries_filter_multi_platform(builder):
    sql = builder()
    assert "rating_platform_count >= 2" in sql


def test_pairwise_queries_cover_all_three_pairs():
    sql = queries.q1_pairwise_agreement()
    assert "google vs tripadvisor" in sql
    assert "google vs thefork" in sql
    assert "tripadvisor vs thefork" in sql


def test_q2_top_pair_threshold_and_orders_desc():
    sql = queries.q2_top_pair("google", "tripadvisor", min_diff=1.0)
    assert "abs(google_rating_5 - tripadvisor_rating_5) > 1.0" in sql
    assert "ORDER BY abs_diff DESC" in sql


def test_q3_uses_correlation_for_mandatory_query():
    sql = queries.q3_correlations()
    assert "corr(rating_range_5, least_reviews)" in sql
    assert "corr(rating_range_5, total_reviews)" in sql


def test_q4_excludes_null_ratings_and_counts_per_platform():
    sql = queries.q4_sparse_summary()
    # Each platform guards both its rating and its review count against null.
    assert "google_rating_5 IS NOT NULL AND google_review_count IS NOT NULL" in sql
    assert "thefork_rating_5 IS NOT NULL AND thefork_review_count IS NOT NULL" in sql


def test_q6_drops_median_uses_mean_with_spread():
    sql = queries.q6_popularity_bins()
    assert "avg(rating_range_5)" in sql
    assert "stddevSamp(rating_range_5)" in sql
    assert "median" not in sql  # median deliberately dropped (<=3 platforms)


def test_q7_uses_real_completeness_not_coordinates():
    sql = queries.q7_rows()
    # Real platform-provided completeness signals.
    assert "google_has_website" in sql
    assert "tripadvisor_photo_count" in sql
    assert "google_review_count" in sql
    # Coordinates must NOT be used as a completeness metric (TA coords were
    # enriched downstream via Nominatim).
    assert "has_coordinates" not in sql


def test_q9_groups_by_normalized_price_tier():
    sql = queries.q9_price_tier()
    assert "GROUP BY price_tier" in sql


def test_q11_correlates_photos_with_reviews_and_rating():
    sql = queries.q11_photo_correlations()
    assert "corrIf(google_photo_count, google_review_count" in sql
    assert "corrIf(tripadvisor_photo_count, tripadvisor_rating_5" in sql
