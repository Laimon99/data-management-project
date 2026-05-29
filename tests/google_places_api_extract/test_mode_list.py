import httpx
import pytest
import respx
from google_places_api_extract.checkpoint import TileCheckpoint
from google_places_api_extract.cli import app
from google_places_api_extract.config import Settings
from google_places_api_extract.mode_list import run_mode_list
from google_places_api_extract.places_client import NEARBY_URL, PlacesClient
from google_places_api_extract.storage import JsonlSeedStore
from pydantic import ValidationError
from typer.testing import CliRunner

from .conftest import make_place


def test_pagination_consumed(settings, tmp_path):
    page1 = {"places": [make_place("p1"), make_place("p2")], "nextPageToken": "tok"}
    page2 = {"places": [make_place("p3")]}
    empty = {"places": []}

    store = JsonlSeedStore(settings.seed_jsonl_path)
    ckpt = TileCheckpoint(settings.checkpoint_dir / "tiles.json")

    with respx.mock() as router:
        # first call → page1, second call → page2 (consumes tok), then empties.
        responses = [httpx.Response(200, json=page1), httpx.Response(200, json=page2)]
        # pad with many empties to cover all subsequent tiles
        responses.extend(httpx.Response(200, json=empty) for _ in range(50))
        router.post(NEARBY_URL).mock(side_effect=responses)
        with PlacesClient(settings) as client:
            report = run_mode_list(settings, store, client, ckpt)

    assert report.unique_places == 3
    ids = sorted(store.iter_place_ids())
    assert ids == ["p1", "p2", "p3"]


def test_duplicate_place_across_tiles_dedupes(settings, tmp_path):
    """Same place returned by every tile should result in one stored doc."""
    store = JsonlSeedStore(settings.seed_jsonl_path)
    ckpt = TileCheckpoint(settings.checkpoint_dir / "tiles.json")

    with respx.mock() as router:
        router.post(NEARBY_URL).respond(200, json={"places": [make_place("dup")]})
        with PlacesClient(settings) as client:
            report = run_mode_list(settings, store, client, ckpt)

    assert report.unique_places == 1
    assert list(store.iter_place_ids()) == ["dup"]


def test_rerun_with_checkpoint_skips_all_tiles(settings, tmp_path):
    store = JsonlSeedStore(settings.seed_jsonl_path)
    ckpt = TileCheckpoint(settings.checkpoint_dir / "tiles.json")

    with respx.mock() as router:
        router.post(NEARBY_URL).respond(200, json={"places": [make_place("p1")]})
        with PlacesClient(settings) as client:
            r1 = run_mode_list(settings, store, client, ckpt)

    # rerun: every tile is in the checkpoint, no API calls expected
    with respx.mock(assert_all_called=False) as router:
        router.post(NEARBY_URL).respond(200, json={"places": [make_place("p1")]})
        with PlacesClient(settings) as client:
            r2 = run_mode_list(settings, store, client, ckpt)

    assert r2.tiles_processed == 0
    assert r2.tiles_skipped == r1.tiles_processed
    assert list(store.iter_place_ids()) == ["p1"]


def test_rerun_without_checkpoint_no_duplicates(settings, tmp_path):
    store = JsonlSeedStore(settings.seed_jsonl_path)
    ckpt1 = TileCheckpoint(settings.checkpoint_dir / "tiles1.json")

    with respx.mock() as router:
        router.post(NEARBY_URL).respond(200, json={"places": [make_place("p1")]})
        with PlacesClient(settings) as client:
            run_mode_list(settings, store, client, ckpt1)

    # fresh checkpoint, store reused — should upsert, not duplicate
    ckpt2 = TileCheckpoint(settings.checkpoint_dir / "tiles2.json")
    with respx.mock() as router:
        router.post(NEARBY_URL).respond(200, json={"places": [make_place("p1")]})
        with PlacesClient(settings) as client:
            run_mode_list(settings, store, client, ckpt2)

    assert list(store.iter_place_ids()) == ["p1"]


def test_missing_api_key_raises_before_network(monkeypatch):
    monkeypatch.delenv("DATAMAN_GOOGLE_PLACES_API_KEY", raising=False)
    with respx.mock(assert_all_called=False) as router:
        route = router.post(NEARBY_URL).respond(200, json={})
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]
        assert route.call_count == 0


def test_cli_missing_api_key_clear_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATAMAN_GOOGLE_PLACES_API_KEY", raising=False)
    runner = CliRunner()
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 1
    assert "DATAMAN_GOOGLE_PLACES_API_KEY" in result.output
