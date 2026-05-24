from typing import Any

import pytest
from pipeline.stage1_seed.config import Settings
from pipeline.stage1_seed.places_client import PlacesClient
from tenacity import wait_none


@pytest.fixture
def settings(monkeypatch, tmp_path) -> Settings:
    monkeypatch.setenv("DATAMAN_GOOGLE_PLACES_API_KEY", "test-key-xyz")
    monkeypatch.setenv("DATAMAN_SEED_JSONL_PATH", str(tmp_path / "seed.jsonl"))
    monkeypatch.setenv("DATAMAN_CHECKPOINT_DIR", str(tmp_path / "ckpt"))
    monkeypatch.setenv("DATAMAN_OUTER_RADIUS_M", "1000")
    monkeypatch.setenv("DATAMAN_SEARCH_RADIUS_M", "750")
    monkeypatch.setenv("DATAMAN_TILE_OVERLAP", "0.3")
    monkeypatch.setenv("DATAMAN_REQUEST_DELAY_S", "0")
    monkeypatch.setenv("DATAMAN_MAX_PAGES_PER_TILE", "3")
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def fast_retries():
    """Disable tenacity backoff on PlacesClient methods so retries are instant."""
    original_post = PlacesClient._post.retry.wait
    original_get = PlacesClient._get.retry.wait
    PlacesClient._post.retry.wait = wait_none()
    PlacesClient._get.retry.wait = wait_none()
    try:
        yield
    finally:
        PlacesClient._post.retry.wait = original_post
        PlacesClient._get.retry.wait = original_get


def make_place(
    pid: str,
    name: str = "Foo",
    lat: float = 45.46,
    lon: float = 9.19,
    rating: float | None = 4.0,
    rating_count: int | None = 50,
) -> dict[str, Any]:
    return {
        "id": pid,
        "displayName": {"text": name, "languageCode": "en"},
        "formattedAddress": "Via Foo 1, Milan",
        "location": {"latitude": lat, "longitude": lon},
        "types": ["restaurant"],
        "primaryType": "restaurant",
        "rating": rating,
        "userRatingCount": rating_count,
        "addressComponents": [
            {"longText": "Milan", "shortText": "MI", "types": ["locality"]},
        ],
    }
