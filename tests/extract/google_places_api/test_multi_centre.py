import json

import respx
from typer.testing import CliRunner

from extract.google_places_api import mode_list
from extract.google_places_api.checkpoint import TileCheckpoint
from extract.google_places_api.cli import app
from extract.google_places_api.config import Settings
from extract.google_places_api.mode_list import resolve_centres, run_mode_list
from extract.google_places_api.places_client import NEARBY_URL, PlacesClient
from extract.google_places_api.storage import JsonlSeedStore
from extract.google_places_api.tiling import Tile

from .conftest import make_place

_NB = json.dumps(
    [
        {"name": "alpha", "lat": 45.46, "lon": 9.19, "outer_radius_m": 800},
        {"name": "beta", "lat": 45.48, "lon": 9.21, "outer_radius_m": 800},
    ]
)


def _settings_with_anchors(base: Settings) -> Settings:
    anchors = Settings(
        google_places_api_key="x",  # type: ignore[arg-type]
        neighbourhoods=json.loads(_NB),
    ).neighbourhoods
    return base.model_copy(update={"neighbourhoods": anchors})


def _store_and_ckpt(settings):
    return (
        JsonlSeedStore(settings.seed_jsonl_path),
        TileCheckpoint(settings.checkpoint_dir / "tiles.json"),
    )


# --- resolve_centres unit coverage -----------------------------------------


def test_resolve_full_is_city_plus_anchors(settings):
    s = _settings_with_anchors(settings)
    city = (s.milan_center_lat, s.milan_center_lon, float(s.outer_radius_m))
    assert resolve_centres(s, "full") == [city, (45.46, 9.19, 800.0), (45.48, 9.21, 800.0)]


def test_resolve_city_only(settings):
    s = _settings_with_anchors(settings)
    assert resolve_centres(s, "city") == [
        (s.milan_center_lat, s.milan_center_lon, float(s.outer_radius_m))
    ]


def test_resolve_neighbourhoods_only(settings):
    s = _settings_with_anchors(settings)
    assert resolve_centres(s, "neighbourhoods") == [(45.46, 9.19, 800.0), (45.48, 9.21, 800.0)]


def test_resolve_full_empty_anchors_is_city(settings):
    # settings fixture pins neighbourhoods=[] -> default scope yields only the city circle
    city = (settings.milan_center_lat, settings.milan_center_lon, float(settings.outer_radius_m))
    assert resolve_centres(settings, "full") == [city]


# --- run_mode_list routing --------------------------------------------------


def test_run_mode_list_passes_resolved_centres(settings, monkeypatch):
    s = _settings_with_anchors(settings)
    captured = {}

    def fake_multi(centres, *, tile_radius_m, overlap):
        captured["centres"] = centres
        captured["tile_radius_m"] = tile_radius_m
        return [Tile(lat=c[0], lon=c[1], radius_m=750) for c in centres]

    monkeypatch.setattr(mode_list, "generate_multi_centre_tiles", fake_multi)

    store, ckpt = _store_and_ckpt(s)
    with respx.mock() as router:
        router.post(NEARBY_URL).respond(200, json={"places": []})
        with PlacesClient(s) as client:
            report = run_mode_list(s, store, client, ckpt, scope="full")

    assert captured["centres"] == resolve_centres(s, "full")
    assert captured["tile_radius_m"] == s.search_radius_m
    assert report.total_tiles == 3


def test_report_total_tiles_matches(settings):
    store, ckpt = _store_and_ckpt(settings)
    with respx.mock() as router:
        router.post(NEARBY_URL).respond(200, json={"places": [make_place("p1")]})
        with PlacesClient(settings) as client:
            report = run_mode_list(settings, store, client, ckpt)
    assert report.total_tiles == report.tiles_processed + report.tiles_skipped


# --- CLI scope selection ----------------------------------------------------


def _list_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAMAN_GOOGLE_PLACES_API_KEY", "test-key-xyz")
    monkeypatch.setenv("DATAMAN_SEED_JSONL_PATH", str(tmp_path / "seed.jsonl"))
    monkeypatch.setenv("DATAMAN_CHECKPOINT_DIR", str(tmp_path / "ckpt"))
    monkeypatch.setenv("DATAMAN_OUTER_RADIUS_M", "1000")
    monkeypatch.setenv("DATAMAN_SEARCH_RADIUS_M", "750")
    monkeypatch.setenv("DATAMAN_TILE_OVERLAP", "0.3")
    monkeypatch.setenv("DATAMAN_NEIGHBOURHOODS", _NB)
    monkeypatch.setenv("DATAMAN_REQUEST_DELAY_S", "0")


def _spy_centres(monkeypatch):
    captured = {}
    real = mode_list.generate_multi_centre_tiles

    def spy(centres, *, tile_radius_m, overlap):
        captured["centres"] = centres
        return real(centres, tile_radius_m=tile_radius_m, overlap=overlap)

    monkeypatch.setattr(mode_list, "generate_multi_centre_tiles", spy)
    return captured


def test_cli_default_covers_city_and_anchors(monkeypatch, tmp_path):
    _list_env(monkeypatch, tmp_path)
    captured = _spy_centres(monkeypatch)
    runner = CliRunner()
    with respx.mock() as router:
        router.post(NEARBY_URL).respond(200, json={"places": []})
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert captured["centres"] == [
        (45.4642, 9.19, 1000.0),
        (45.46, 9.19, 800.0),
        (45.48, 9.21, 800.0),
    ]


def test_cli_whole_city_only(monkeypatch, tmp_path):
    _list_env(monkeypatch, tmp_path)
    captured = _spy_centres(monkeypatch)
    runner = CliRunner()
    with respx.mock() as router:
        router.post(NEARBY_URL).respond(200, json={"places": []})
        result = runner.invoke(app, ["list", "--whole-city"])
    assert result.exit_code == 0
    assert captured["centres"] == [(45.4642, 9.19, 1000.0)]


def test_cli_all_neighbourhoods_only(monkeypatch, tmp_path):
    _list_env(monkeypatch, tmp_path)
    captured = _spy_centres(monkeypatch)
    runner = CliRunner()
    with respx.mock() as router:
        router.post(NEARBY_URL).respond(200, json={"places": []})
        result = runner.invoke(app, ["list", "--all-neighbourhoods"])
    assert result.exit_code == 0
    assert captured["centres"] == [(45.46, 9.19, 800.0), (45.48, 9.21, 800.0)]


def test_cli_single_neighbourhood(monkeypatch, tmp_path):
    _list_env(monkeypatch, tmp_path)
    captured = _spy_centres(monkeypatch)
    runner = CliRunner()
    with respx.mock() as router:
        router.post(NEARBY_URL).respond(200, json={"places": []})
        result = runner.invoke(app, ["list", "--neighbourhood", "beta"])
    assert result.exit_code == 0
    assert captured["centres"] == [(45.48, 9.21, 800.0)]


def test_cli_unknown_neighbourhood_exits_2(monkeypatch, tmp_path):
    _list_env(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["list", "--neighbourhood", "nope"])
    assert result.exit_code == 2
    assert "Unknown neighbourhood" in result.output


def test_cli_conflicting_scope_flags_exit_2(monkeypatch, tmp_path):
    _list_env(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["list", "--whole-city", "--all-neighbourhoods"])
    assert result.exit_code == 2
