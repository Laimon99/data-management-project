import respx
from google_places_api_extract.checkpoint import DetailCheckpoint
from google_places_api_extract.mode_detail import run_mode_detail
from google_places_api_extract.places_client import PlacesClient
from google_places_api_extract.schema import SeedDoc
from google_places_api_extract.storage import JsonlSeedStore


def _seed(pid: str) -> SeedDoc:
    return SeedDoc(place_id=pid, name="Foo", latitude=45.0, longitude=9.0)


def _details_url(pid: str) -> str:
    return f"https://places.googleapis.com/v1/places/{pid}"


def test_partial_details_stored_without_crash(settings):
    store = JsonlSeedStore(settings.seed_jsonl_path)
    ckpt = DetailCheckpoint(settings.checkpoint_dir / "detail.txt")
    store.upsert(_seed("abc"))

    raw = {
        "rating": None,
        "userRatingCount": None,
        "websiteUri": None,
        "regularOpeningHours": None,
        "reviews": None,
    }
    with respx.mock() as router:
        router.get(_details_url("abc")).respond(200, json=raw)
        with PlacesClient(settings) as client:
            report = run_mode_detail(settings, store, client, ckpt, place_ids=["abc"])

    assert report.enriched == 1
    after = store.get("abc")
    assert after is not None
    assert after.details == raw
    assert after.rating is None


def test_detail_idempotent_via_checkpoint(settings):
    store = JsonlSeedStore(settings.seed_jsonl_path)
    ckpt = DetailCheckpoint(settings.checkpoint_dir / "detail.txt")
    store.upsert(_seed("abc"))
    original_collected = store.get("abc").seed_collected_at

    raw = {"rating": 4.5, "userRatingCount": 100}
    with respx.mock() as router:
        router.get(_details_url("abc")).respond(200, json=raw)
        with PlacesClient(settings) as client:
            run_mode_detail(settings, store, client, ckpt, place_ids=["abc"])
        first_fetched = store.get("abc").details_fetched_at

        with PlacesClient(settings) as client:
            r2 = run_mode_detail(settings, store, client, ckpt, place_ids=["abc"])

    assert r2.skipped_already_done == 1
    assert r2.enriched == 0
    after = store.get("abc")
    assert after.seed_collected_at == original_collected
    assert after.details_fetched_at == first_fetched


def test_detail_continues_after_per_place_failure(settings, fast_retries):
    store = JsonlSeedStore(settings.seed_jsonl_path)
    ckpt = DetailCheckpoint(settings.checkpoint_dir / "detail.txt")
    store.upsert(_seed("bad"))
    store.upsert(_seed("good"))

    with respx.mock() as router:
        router.get(_details_url("bad")).respond(500, json={})
        router.get(_details_url("good")).respond(200, json={"rating": 4.0})
        with PlacesClient(settings) as client:
            report = run_mode_detail(settings, store, client, ckpt, place_ids=["bad", "good"])

    assert report.enriched == 1
    assert len(report.errors) == 1
    assert report.errors[0]["place_id"] == "bad"
    assert store.get("good").rating == 4.0
    assert store.get("bad").details is None


def test_detail_skips_unknown_place_id(settings):
    store = JsonlSeedStore(settings.seed_jsonl_path)
    ckpt = DetailCheckpoint(settings.checkpoint_dir / "detail.txt")

    with respx.mock(assert_all_called=False) as router:
        router.get(_details_url("ghost")).respond(200, json={"rating": 4.0})
        with PlacesClient(settings) as client:
            report = run_mode_detail(settings, store, client, ckpt, place_ids=["ghost"])

    assert report.skipped_unknown == 1
    assert report.enriched == 0
