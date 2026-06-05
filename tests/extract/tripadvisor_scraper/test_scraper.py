from pathlib import Path
from types import SimpleNamespace

import pytest

from extract.tripadvisor_scraper import scraper


@pytest.fixture(autouse=True)
def restore_scraper_paths():
    original_paths = {
        "DATA_DIR": scraper.DATA_DIR,
        "URL_FILE": scraper.URL_FILE,
        "JSON_FILE": scraper.JSON_FILE,
        "CHECKPOINT_FILE": scraper.CHECKPOINT_FILE,
        "OLD_USER_DATA_DIR": scraper.OLD_USER_DATA_DIR,
        "USER_DATA_DIR": scraper.USER_DATA_DIR,
    }
    yield
    for name, value in original_paths.items():
        setattr(scraper, name, value)


def test_order_urls_top_keeps_input_order():
    assert scraper.order_urls(["a", "b", "c"], "top") == ["a", "b", "c"]


def test_default_data_dir_points_to_raw_tripadvisor():
    assert scraper.DEFAULT_DATA_DIR == Path("data/raw/tripadvisor")


def test_order_urls_bottom_reverses_input_order():
    assert scraper.order_urls(["a", "b", "c"], "bottom") == ["c", "b", "a"]


def test_resolve_chromium_browser_accepts_existing_override(tmp_path):
    browser = tmp_path / "chrome"
    browser.touch()

    assert scraper.resolve_chromium_browser(browser) == browser


def test_resolve_chromium_browser_rejects_missing_override(tmp_path):
    with pytest.raises(FileNotFoundError):
        scraper.resolve_chromium_browser(tmp_path / "missing-browser")


def test_resolve_chromium_browser_returns_first_existing_path_in_priority(monkeypatch):
    # Brave (priority 1) and Chrome both "exist"; Brave must win.
    brave_path = scraper.CHROMIUM_BROWSERS[0]["paths"]["Darwin"][0]
    existing = {brave_path, scraper.CHROMIUM_BROWSERS[1]["paths"]["Darwin"][0]}

    monkeypatch.setattr(scraper.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(scraper.Path, "exists", lambda self: self in existing)

    assert scraper.resolve_chromium_browser() == brave_path


def test_resolve_chromium_browser_falls_through_to_which(monkeypatch):
    monkeypatch.setattr(scraper.platform, "system", lambda: "Linux")
    monkeypatch.setattr(scraper.Path, "exists", lambda self: False)
    monkeypatch.setattr(
        scraper.shutil,
        "which",
        lambda name: "/usr/bin/google-chrome" if name == "google-chrome" else None,
    )

    assert scraper.resolve_chromium_browser() == Path("/usr/bin/google-chrome")


def test_resolve_chromium_browser_returns_none_when_nothing_found(monkeypatch):
    monkeypatch.setattr(scraper.platform, "system", lambda: "Linux")
    monkeypatch.setattr(scraper.Path, "exists", lambda self: False)
    monkeypatch.setattr(scraper.shutil, "which", lambda name: None)

    assert scraper.resolve_chromium_browser() is None


def test_parse_args_accepts_browser_path(monkeypatch):
    monkeypatch.setattr(scraper.sys, "argv", ["prog", "--browser-path", "/path/to/chrome"])
    args = scraper.parse_args()

    assert args.browser_path == "/path/to/chrome"
    assert args.brave_path is None


def test_parse_args_accepts_legacy_brave_path(monkeypatch):
    monkeypatch.setattr(scraper.sys, "argv", ["prog", "--brave-path", "/path/to/brave"])
    args = scraper.parse_args()

    assert args.brave_path == "/path/to/brave"


def test_resolve_browser_path_override_prefers_browser_path():
    args = SimpleNamespace(browser_path="/new/chrome", brave_path=None)

    assert scraper.resolve_browser_path_override(args) == "/new/chrome"


def test_resolve_browser_path_override_falls_back_to_legacy(capsys):
    args = SimpleNamespace(browser_path=None, brave_path="/old/brave")

    assert scraper.resolve_browser_path_override(args) == "/old/brave"
    assert "deprecato" in capsys.readouterr().err


def test_migrate_profile_dir_renames_legacy_directory(tmp_path, monkeypatch):
    old_dir = tmp_path / "brave_automation_profile"
    new_dir = tmp_path / "browser_automation_profile"
    old_dir.mkdir()
    (old_dir / "cookies").write_text("session", encoding="utf-8")

    monkeypatch.setattr(scraper, "OLD_USER_DATA_DIR", old_dir)
    monkeypatch.setattr(scraper, "USER_DATA_DIR", new_dir)

    scraper.migrate_profile_dir()

    assert not old_dir.exists()
    assert (new_dir / "cookies").read_text(encoding="utf-8") == "session"


def test_configure_runtime_paths_sets_default_paths(tmp_path):
    data_dir = tmp_path / "data"
    scraper.configure_runtime_paths(data_dir=data_dir)

    assert scraper.DATA_DIR == data_dir.resolve()
    assert scraper.URL_FILE == data_dir.resolve() / "tripadvisor_list_restaurant.txt"
    assert scraper.JSON_FILE == data_dir.resolve() / "tripadvisor_scraper_results.json"
    assert scraper.CHECKPOINT_FILE == data_dir.resolve() / "tripadvisor_checkpoint.json"
    assert scraper.USER_DATA_DIR == data_dir.resolve() / "browser_automation_profile"


def test_configure_runtime_paths_accepts_custom_url_file(tmp_path):
    data_dir = tmp_path / "data"
    custom_url_file = tmp_path / "custom_urls.txt"
    scraper.configure_runtime_paths(data_dir=data_dir, url_file=custom_url_file)

    assert scraper.URL_FILE == custom_url_file.resolve()
