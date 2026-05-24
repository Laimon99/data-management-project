from pipeline.stage1_seed.schema import SeedDoc, merge_details
from pipeline.stage1_seed.storage import JsonlSeedStore


def _doc(pid: str = "x", **kwargs) -> SeedDoc:
    base = {"place_id": pid, "name": "Foo", "latitude": 45.0, "longitude": 9.0}
    base.update(kwargs)
    return SeedDoc(**base)


def test_jsonl_roundtrip(tmp_path):
    path = tmp_path / "seed.jsonl"
    s1 = JsonlSeedStore(path)
    s1.upsert(_doc("a"))
    s1.upsert(_doc("b", name="Bar"))

    s2 = JsonlSeedStore(path)
    assert s2.get("a").name == "Foo"
    assert s2.get("b").name == "Bar"
    assert sorted(s2.iter_place_ids()) == ["a", "b"]


def test_merge_details_preserves_seed(tmp_path):
    path = tmp_path / "seed.jsonl"
    s = JsonlSeedStore(path)
    s.upsert(_doc("a"))
    original_collected = s.get("a").seed_collected_at

    raw = {"rating": 4.5, "userRatingCount": 100, "websiteUri": "http://x"}
    s.upsert(merge_details(s.get("a"), raw))

    after = s.get("a")
    assert after.rating == 4.5
    assert after.user_rating_count == 100
    assert after.details == raw
    assert after.details_fetched_at is not None
    assert after.seed_collected_at == original_collected
    assert after.name == "Foo"


def test_seed_rerun_preserves_details(tmp_path):
    """Re-running Mode 1 (fresh SeedDoc, no details) must keep existing details."""
    path = tmp_path / "seed.jsonl"
    s = JsonlSeedStore(path)
    s.upsert(_doc("a"))
    s.upsert(merge_details(s.get("a"), {"rating": 4.5}))

    s.upsert(_doc("a", name="Foo Updated"))
    after = s.get("a")
    assert after.name == "Foo Updated"
    assert after.details == {"rating": 4.5}


def test_get_missing_returns_none(tmp_path):
    s = JsonlSeedStore(tmp_path / "seed.jsonl")
    assert s.get("does-not-exist") is None


def test_partial_details_no_crash(tmp_path):
    """Place Details with several null fields should not crash merge_details."""
    s = JsonlSeedStore(tmp_path / "seed.jsonl")
    s.upsert(_doc("a"))

    raw = {
        "rating": None,
        "userRatingCount": None,
        "websiteUri": None,
        "regularOpeningHours": None,
        "reviews": None,
        "priceLevel": None,
    }
    merged = merge_details(s.get("a"), raw)
    s.upsert(merged)

    after = s.get("a")
    assert after.details == raw
    assert after.rating is None
