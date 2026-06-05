"""Unit tests for the pure helpers + the dataset loop (no network).

The Nominatim call in ``geocode_dataset`` is patched, so these run offline.
"""

import json
from collections import OrderedDict

import pytest

from transform.tripadvisor_geocode.config import NAN_VALUE, GeocodeSettings
from transform.tripadvisor_geocode.geocode import (
    geocode_dataset,
    is_nan,
    reorder_with_coords,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, True),
        ("NaN", True),
        ("nan", True),
        ("  NaN  ", True),
        ("Via Roma 1", False),
        ("", False),
    ],
)
def test_is_nan(value, expected):
    assert is_nan(value) is expected


def test_reorder_inserts_coords_after_address():
    record = OrderedDict([("restaurant_name", "X"), ("address", "Via Roma 1"), ("website", "x.it")])
    out = reorder_with_coords(record, "45.0", "9.0")
    assert list(out.keys()) == [
        "restaurant_name",
        "address",
        "latitude",
        "longitude",
        "website",
    ]
    assert out["latitude"] == "45.0"
    assert out["longitude"] == "9.0"


def test_reorder_appends_when_no_address():
    record = OrderedDict([("restaurant_name", "X")])
    out = reorder_with_coords(record, "1", "2")
    assert out["latitude"] == "1"
    assert out["longitude"] == "2"


def test_geocode_dataset_classifies_records(tmp_path, monkeypatch):
    data = [
        {"restaurant_name": "Found", "address": "Piazza Duomo, Milano"},
        {"restaurant_name": "NotFound", "address": "nowhere-xyz"},
        {"restaurant_name": "Skipped", "address": "NaN"},
    ]
    in_path = tmp_path / "in.json"
    out_path = tmp_path / "out.json"
    in_path.write_text(json.dumps(data), encoding="utf-8")

    class _Loc:
        latitude = 45.46
        longitude = 9.19

    def fake_geocode(self, address, timeout=10):  # noqa: ARG001
        return _Loc() if address == "Piazza Duomo, Milano" else None

    monkeypatch.setattr("transform.tripadvisor_geocode.geocode.Nominatim.geocode", fake_geocode)
    settings = GeocodeSettings(delay_seconds=0.0)

    report = geocode_dataset(in_path, out_path, settings)

    assert (report.total, report.found, report.not_found, report.skipped) == (3, 1, 1, 1)
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written[0]["latitude"] == "45.46"
    assert written[1]["latitude"] == NAN_VALUE
    assert written[2]["latitude"] == NAN_VALUE


def test_geocode_dataset_missing_input(tmp_path):
    with pytest.raises(FileNotFoundError):
        geocode_dataset(tmp_path / "nope.json", tmp_path / "o.json", GeocodeSettings())
