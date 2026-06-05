from pathlib import Path

import pytest

from mongo_load.config import LoaderSettings
from mongo_load.sources import SOURCES, resolve


def test_settings_defaults_without_api_key(monkeypatch):
    # Even with a Google key absent, settings must construct fine.
    monkeypatch.delenv("DATAMAN_GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.delenv("DATAMAN_MONGO_URI", raising=False)
    monkeypatch.delenv("DATAMAN_MONGO_DB", raising=False)

    settings = LoaderSettings(_env_file=None)

    assert settings.mongo_uri == "mongodb://localhost:27017"
    assert settings.mongo_db == "dataman"


def test_settings_reads_env_prefix(monkeypatch):
    monkeypatch.setenv("DATAMAN_MONGO_URI", "mongodb://example:27017")
    monkeypatch.setenv("DATAMAN_MONGO_DB", "other")

    settings = LoaderSettings(_env_file=None)

    assert settings.mongo_uri == "mongodb://example:27017"
    assert settings.mongo_db == "other"


def test_registry_resolves_expected_specs():
    assert set(SOURCES) == {"google", "tripadvisor", "thefork"}

    google = SOURCES["google"]
    assert google.raw_file == Path("data/raw/google_places/restaurants_seed.jsonl")
    assert google.fmt == "jsonl"
    assert google.key_field == "place_id"
    assert google.collection == "restaurants_raw_google"

    tripadvisor = SOURCES["tripadvisor"]
    assert tripadvisor.fmt == "json_array"
    assert tripadvisor.key_field == "source_url"
    assert tripadvisor.collection == "restaurants_raw_tripadvisor"

    thefork = SOURCES["thefork"]
    assert thefork.fmt == "json_array"
    assert thefork.key_field == "source_id"
    assert thefork.collection == "restaurants_raw_thefork"


def test_resolve_single_and_all():
    assert [s.name for s in resolve("thefork")] == ["thefork"]
    assert {s.name for s in resolve("all")} == {"google", "tripadvisor", "thefork"}


def test_resolve_unknown_raises():
    with pytest.raises(ValueError, match="Unknown source"):
        resolve("bogus")
