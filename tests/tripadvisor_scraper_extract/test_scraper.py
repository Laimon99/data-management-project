from pathlib import Path

import pytest

from tripadvisor_scraper_extract import scraper


@pytest.fixture(autouse=True)
def restore_scraper_paths():
    original_paths = {
        "DATA_DIR": scraper.DATA_DIR,
        "URL_FILE": scraper.URL_FILE,
        "JSON_FILE": scraper.JSON_FILE,
        "CHECKPOINT_FILE": scraper.CHECKPOINT_FILE,
        "USER_DATA_DIR": scraper.USER_DATA_DIR,
    }
    yield
    for name, value in original_paths.items():
        setattr(scraper, name, value)


def test_order_urls_top_keeps_input_order():
    assert scraper.order_urls(["a", "b", "c"], "top") == ["a", "b", "c"]


def test_order_urls_bottom_reverses_input_order():
    assert scraper.order_urls(["a", "b", "c"], "bottom") == ["c", "b", "a"]


def test_resolve_brave_path_accepts_existing_override(tmp_path):
    brave = tmp_path / "brave"
    brave.touch()

    assert scraper.resolve_brave_path(brave) == brave


def test_resolve_brave_path_rejects_missing_override(tmp_path):
    with pytest.raises(FileNotFoundError):
        scraper.resolve_brave_path(tmp_path / "missing-brave")


def test_configure_runtime_paths_copies_bundled_url_list(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled_urls.txt"
    bundled.write_text("https://example.test/restaurant\n", encoding="utf-8")
    monkeypatch.setattr(scraper, "BUNDLED_URL_FILE", bundled)

    data_dir = tmp_path / "data"
    scraper.configure_runtime_paths(data_dir=data_dir)

    assert scraper.DATA_DIR == data_dir.resolve()
    assert scraper.URL_FILE == data_dir.resolve() / "tripadvisor_list_restaurant.txt"
    assert scraper.URL_FILE.read_text(encoding="utf-8") == "https://example.test/restaurant\n"
    assert scraper.JSON_FILE == data_dir.resolve() / "tripadvisor_scraper_results.json"
    assert scraper.CHECKPOINT_FILE == data_dir.resolve() / "tripadvisor_checkpoint.json"
    assert scraper.USER_DATA_DIR == data_dir.resolve() / "brave_automation_profile"


def test_configure_runtime_paths_accepts_custom_url_file(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled_urls.txt"
    bundled.write_text("https://example.test/restaurant\n", encoding="utf-8")
    monkeypatch.setattr(scraper, "BUNDLED_URL_FILE", bundled)

    data_dir = tmp_path / "data"
    custom_url_file = tmp_path / "custom_urls.txt"
    scraper.configure_runtime_paths(data_dir=data_dir, url_file=custom_url_file)

    assert scraper.URL_FILE == custom_url_file.resolve()
    assert Path(custom_url_file).read_text(encoding="utf-8") == "https://example.test/restaurant\n"
