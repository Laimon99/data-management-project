"""Tests for the canonical cuisine taxonomy + cross-platform merge."""

from __future__ import annotations

from transform.unified_dataset.cuisine import (
    OTHER,
    RAW_TO_BUCKET,
    canonical_cuisine_list,
    merge_cuisine,
    normalize_labels,
)


def test_gendered_and_multilingual_variants_collapse_to_one_bucket():
    # Tripadvisor feminine, TheFork masculine, Google English -> all "Italian".
    assert RAW_TO_BUCKET["italiana"] == "Italian"
    assert RAW_TO_BUCKET["italiano"] == "Italian"
    assert RAW_TO_BUCKET["italian_restaurant"] == "Italian"
    assert RAW_TO_BUCKET["asiatica"] == "Asian"
    assert RAW_TO_BUCKET["asiatico"] == "Asian"


def test_regional_italians_map_to_italian():
    for regional in ("lombardo", "toscano", "napoletano", "siciliano", "milanese"):
        assert RAW_TO_BUCKET[regional] == "Italian"


def test_normalize_labels_tripadvisor_unmapped_becomes_other():
    buckets, unmapped = normalize_labels(["Italiana", "Totally Made Up"], allow_other=True)
    assert "Italian" in buckets
    assert unmapped == ["totally made up"]
    # all-unknown source still yields a single Other tag (it *had* a cuisine opinion)
    buckets, _ = normalize_labels(["Nonexistent Cuisine"], allow_other=True)
    assert buckets == [OTHER]


def test_normalize_google_drops_non_food_types_silently():
    buckets, unmapped = normalize_labels(
        ["restaurant", "bar", "night_club", "food_store", "florist"], allow_other=False
    )
    assert buckets == ["Café/Bakery/Bar"]  # only 'bar' is a food/drink bucket
    assert unmapped == ["night_club", "food_store", "florist"]


def test_merge_specificity_pizza_beats_umbrella_italian():
    # A pizzeria tagged both Italian and Pizza -> primary Pizza.
    out = merge_cuisine(
        ["Italiana", "Pizza"],
        None,
        {"primary_type": "restaurant", "types": ["pizza_restaurant", "italian_restaurant"]},
    )
    assert out["tags"] == ["Italian", "Pizza"]
    assert out["primary"] == "Pizza"
    assert out["agreement"] == "agree"


def test_merge_specific_child_beats_generic_asian():
    out = merge_cuisine(
        ["Asiatica"], None, {"primary_type": "restaurant", "types": ["chinese_restaurant"]}
    )
    assert out["primary"] == "Chinese"  # Chinese (specific) beats Asian (umbrella)


def test_merge_tie_breaks_on_source_precedence():
    # Two equally specific buckets, one per source -> Tripadvisor wins.
    out = merge_cuisine(["Cinese"], ["Giapponese"], None)
    assert out["primary"] == "Chinese"
    assert out["primary_source"] == "tripadvisor"
    assert out["agreement"] == "disagree"


def test_merge_google_only_uses_types_fallback():
    out = merge_cuisine(None, None, {"primary_type": "restaurant", "types": ["sushi_restaurant"]})
    assert out["primary"] == "Japanese"
    assert out["primary_source"] == "google"
    assert out["n_sources"] == 1
    assert out["agreement"] == "single"


def test_merge_no_cuisine_anywhere():
    out = merge_cuisine(None, None, {"primary_type": "restaurant", "types": ["point_of_interest"]})
    assert out["tags"] == []
    assert out["primary"] == ""
    assert out["n_sources"] == 0
    assert out["agreement"] == "single"


def test_cafe_bar_bucket_for_google_dining_types():
    out = merge_cuisine(None, None, {"primary_type": "cafe", "types": ["cafe", "coffee_shop"]})
    assert out["primary"] == "Café/Bakery/Bar"


def test_canonical_list_is_sorted_and_nontrivial():
    buckets = canonical_cuisine_list()
    assert buckets == sorted(buckets)
    assert "Italian" in buckets and "Pizza" in buckets
    assert OTHER not in buckets  # Other is a fallback, not a declared bucket
