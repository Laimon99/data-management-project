from pathlib import Path

from google_places_api_extract.config import Settings


def test_default_raw_data_paths(monkeypatch):
    monkeypatch.setenv("DATAMAN_GOOGLE_PLACES_API_KEY", "test-key")
    monkeypatch.delenv("DATAMAN_SEED_JSONL_PATH", raising=False)
    monkeypatch.delenv("DATAMAN_CHECKPOINT_DIR", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.seed_jsonl_path == Path("data/raw/google_places/restaurants_seed.jsonl")
    assert settings.checkpoint_dir == Path("data/raw/google_places/checkpoints")
