import json
from functools import partial

import mongomock
from pymongo.errors import ServerSelectionTimeoutError
from typer.testing import CliRunner

from load.mongo import cli
from load.mongo.loader import load_source, serial_upsert
from load.mongo.sources import SourceSpec

runner = CliRunner()


def _spec(path) -> SourceSpec:
    return SourceSpec(
        name="thefork",
        raw_file=path,
        fmt="json_array",
        key_field="source_id",
        collection="restaurants_raw_thefork",
    )


def test_cli_unknown_source_exits_nonzero():
    result = runner.invoke(cli.app, ["bogus"])
    assert result.exit_code == 2
    assert "Unknown source" in result.output


def test_cli_missing_file_exits_nonzero(monkeypatch, tmp_path):
    missing = tmp_path / "nope.json"
    monkeypatch.setattr(cli, "resolve", lambda sel: [_spec(missing)])

    result = runner.invoke(cli.app, ["thefork"])

    assert result.exit_code == 1
    assert "not found" in result.output


def test_cli_happy_path(monkeypatch, tmp_path):
    path = tmp_path / "tf.json"
    path.write_text(json.dumps([{"source_id": "x"}, {"source_id": "y"}]), encoding="utf-8")
    spec = _spec(path)
    monkeypatch.setattr(cli, "resolve", lambda sel: [spec])

    coll = mongomock.MongoClient()["dataman"]["restaurants_raw_thefork"]
    monkeypatch.setattr(cli, "open_collection", lambda settings, s: (coll.database.client, coll))
    # The CLI uses the default bulk writer; mongomock can't run bulk_write, so force
    # the serial writer for this wiring test (the bulk path has its own integration test).
    monkeypatch.setattr(cli, "load_source", partial(load_source, writer=serial_upsert))

    result = runner.invoke(cli.app, ["thefork"])

    assert result.exit_code == 0, result.output
    assert coll.count_documents({}) == 2
    assert '"inserted": 2' in result.output


def test_cli_mongo_unreachable_exits_nonzero(monkeypatch, tmp_path):
    # Even with an empty file (no writes), an unreachable Mongo must fail fast.
    path = tmp_path / "tf.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(cli, "resolve", lambda sel: [_spec(path)])

    def _boom(settings, spec):
        raise ServerSelectionTimeoutError("no servers")

    monkeypatch.setattr(cli, "open_collection", _boom)

    result = runner.invoke(cli.app, ["thefork"])

    assert result.exit_code == 1
    assert "MongoDB error" in result.output
