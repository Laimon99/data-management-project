import json
from datetime import datetime as real_datetime
from datetime import timedelta
from functools import partial
from pathlib import Path

import mongomock
import pytest
from pymongo.errors import ServerSelectionTimeoutError

from load.mongo.config import LoaderSettings
from load.mongo.loader import load_source, open_collection, serial_upsert
from load.mongo.sources import SOURCES, SourceSpec

# mongomock 4.3.0 cannot execute bulk_write (the default writer), so unit tests use
# the serial writer, which produces identical collection state. The batched default
# (bulk_upsert) is verified against a real MongoDB in test_integration.py.
_load = partial(load_source, writer=serial_upsert)


def _collection():
    client = mongomock.MongoClient()
    return client["dataman"]["test_coll"]


def _jsonl_spec(path: Path) -> SourceSpec:
    return SourceSpec(
        name="google",
        raw_file=path,
        fmt="jsonl",
        key_field="place_id",
        collection="restaurants_raw_google",
    )


def _array_spec(path: Path) -> SourceSpec:
    return SourceSpec(
        name="thefork",
        raw_file=path,
        fmt="json_array",
        key_field="source_id",
        collection="restaurants_raw_thefork",
    )


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _write_array(path: Path, records: list[dict]) -> None:
    path.write_text(json.dumps(records), encoding="utf-8")


def test_happy_path_jsonl(tmp_path):
    path = tmp_path / "seed.jsonl"
    _write_jsonl(path, [{"place_id": "a", "name": "Foo"}, {"place_id": "b", "name": "Bar"}])
    coll = _collection()

    report = _load(_jsonl_spec(path), coll)

    assert report.read == 2
    assert report.inserted == 2
    assert coll.count_documents({}) == 2
    doc = coll.find_one({"_id": "a"})
    assert doc["_id"] == "a"
    assert doc["place_id"] == "a"
    assert doc["name"] == "Foo"


def test_happy_path_json_array(tmp_path):
    path = tmp_path / "tf.json"
    _write_array(path, [{"source_id": "x", "n": 1}, {"source_id": "y", "n": 2}])
    coll = _collection()

    report = _load(_array_spec(path), coll)

    assert report.read == 2
    assert coll.count_documents({}) == 2
    assert {d["_id"] for d in coll.find({})} == {"x", "y"}


def test_load_metadata_attached_without_clobbering(tmp_path):
    path = tmp_path / "seed.jsonl"
    _write_jsonl(path, [{"place_id": "a", "name": "Foo"}])
    coll = _collection()

    _load(_jsonl_spec(path), coll)

    doc = coll.find_one({"_id": "a"})
    assert "_loaded_at" in doc
    assert doc["_source_file"] == str(path)
    # Source fields untouched.
    assert doc["name"] == "Foo"
    assert doc["place_id"] == "a"


def test_idempotency(tmp_path, monkeypatch):
    path = tmp_path / "seed.jsonl"
    _write_jsonl(path, [{"place_id": "a"}, {"place_id": "b"}])
    coll = _collection()

    first = _load(_jsonl_spec(path), coll)

    # Advance the clock by 1s before the re-run so `_loaded_at` differs at
    # millisecond resolution (mongomock truncates to ms, like real MongoDB);
    # otherwise a same-millisecond re-run would report modified_count 0.
    import load.mongo.loader as loader_mod

    class _Clock:
        @staticmethod
        def now(tz=None):
            return real_datetime.now(tz) + timedelta(seconds=1)

    monkeypatch.setattr(loader_mod, "datetime", _Clock)
    second = _load(_jsonl_spec(path), coll)

    # No duplicates, and the re-run replaces existing docs rather than inserting.
    assert coll.count_documents({}) == 2
    assert first.inserted == 2
    assert second.inserted == 0
    assert second.modified == 2


def test_malformed_jsonl_line_skipped(tmp_path):
    path = tmp_path / "seed.jsonl"
    path.write_text('{"place_id": "a"}\nnot json\n{"place_id": "b"}\n', encoding="utf-8")
    coll = _collection()

    report = _load(_jsonl_spec(path), coll)

    assert coll.count_documents({}) == 2
    assert report.skipped == 1
    assert report.skipped_reasons == {"malformed_line": 1}


@pytest.mark.parametrize("bad", [{}, {"place_id": None}, {"place_id": "   "}])
def test_missing_natural_key_skipped(tmp_path, bad):
    path = tmp_path / "seed.jsonl"
    _write_jsonl(path, [{"place_id": "a"}, bad])
    coll = _collection()

    report = _load(_jsonl_spec(path), coll)

    assert coll.count_documents({}) == 1
    assert report.skipped == 1
    assert report.skipped_reasons == {"missing_key": 1}
    # No auto-generated ObjectId document.
    assert coll.find_one({"_id": "a"}) is not None


def test_duplicate_keys_last_write_wins(tmp_path):
    path = tmp_path / "seed.jsonl"
    _write_jsonl(path, [{"place_id": "a", "v": 1}, {"place_id": "a", "v": 2}])
    coll = _collection()

    _load(_jsonl_spec(path), coll)

    assert coll.count_documents({}) == 1
    assert coll.find_one({"_id": "a"})["v"] == 2


def test_reset_clears_collection(tmp_path):
    path = tmp_path / "seed.jsonl"
    _write_jsonl(path, [{"place_id": "a"}])
    coll = _collection()
    coll.insert_one({"_id": "stale", "place_id": "stale"})

    _load(_jsonl_spec(path), coll, reset=True)

    assert coll.count_documents({}) == 1
    assert coll.find_one({"_id": "stale"}) is None


def test_empty_file_zero_count(tmp_path):
    path = tmp_path / "seed.jsonl"
    path.write_text("", encoding="utf-8")
    coll = _collection()

    report = _load(_jsonl_spec(path), coll)

    assert report.read == 0
    assert report.inserted == 0
    assert coll.count_documents({}) == 0


def test_loads_many_records(tmp_path):
    path = tmp_path / "seed.jsonl"
    _write_jsonl(path, [{"place_id": str(i)} for i in range(25)])
    coll = _collection()

    report = _load(_jsonl_spec(path), coll)

    assert report.read == 25
    assert report.inserted == 25
    assert coll.count_documents({}) == 25


def test_corrupt_json_array_raises_clear_error(tmp_path):
    path = tmp_path / "tf.json"
    path.write_text('[{"source_id": "a"}, {"source_id":', encoding="utf-8")  # truncated
    coll = _collection()

    with pytest.raises(ValueError, match="not valid JSON"):
        _load(_array_spec(path), coll)


def test_non_list_json_array_raises_clear_error(tmp_path):
    path = tmp_path / "tf.json"
    path.write_text('{"results": []}', encoding="utf-8")  # object, not a top-level array
    coll = _collection()

    with pytest.raises(ValueError, match="expected a top-level JSON array"):
        _load(_array_spec(path), coll)


def test_open_collection_pings_and_returns(monkeypatch):
    monkeypatch.setattr("pymongo.MongoClient", mongomock.MongoClient)

    client, coll = open_collection(LoaderSettings(_env_file=None), SOURCES["thefork"])

    assert coll.name == "restaurants_raw_thefork"
    client.close()


def test_open_collection_closes_on_ping_failure(monkeypatch):
    closed = {"value": False}

    class _Admin:
        def command(self, *args, **kwargs):
            raise ServerSelectionTimeoutError("no servers")

    class _Client:
        admin = _Admin()

        def close(self):
            closed["value"] = True

    monkeypatch.setattr("pymongo.MongoClient", lambda *a, **k: _Client())

    with pytest.raises(ServerSelectionTimeoutError):
        open_collection(LoaderSettings(_env_file=None), SOURCES["thefork"])
    assert closed["value"] is True
