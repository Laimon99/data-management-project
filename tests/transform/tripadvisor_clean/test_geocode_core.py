"""Unit tests for the geocoding core (no Mongo; Nominatim stubbed)."""

import pytest
from geopy.exc import GeocoderTimedOut

from transform.tripadvisor_clean.config import CleanSettings
from transform.tripadvisor_clean.geocode import (
    build_query,
    geocode_address,
    geocode_one,
    is_nan,
)


class _Loc:
    def __init__(self, lat, lon):
        self.latitude = lat
        self.longitude = lon


class _Geocoder:
    """Stub geocoder; records calls and replays a scripted sequence of results."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def geocode(self, query, timeout=10):  # noqa: ARG002
        self.calls.append(query)
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _settings():
    return CleanSettings(_env_file=None)


@pytest.mark.parametrize(
    "value,expected",
    [(None, True), ("NaN", True), ("nan", True), ("  NaN  ", True), ("Via Roma 1", False)],
)
def test_is_nan(value, expected):
    assert is_nan(value) is expected


def test_geocode_address_success_returns_floats(monkeypatch):
    monkeypatch.setattr("transform.tripadvisor_clean.geocode.time.sleep", lambda _s: None)
    geocoder = _Geocoder([_Loc(45.46, 9.19)])

    lat, lon = geocode_address(
        geocoder, "Piazza Duomo, Milano", timeout=10, max_retries=2, delay_seconds=1.2
    )

    assert (lat, lon) == (45.46, 9.19)
    assert isinstance(lat, float) and isinstance(lon, float)


def test_geocode_address_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("transform.tripadvisor_clean.geocode.time.sleep", lambda _s: None)
    geocoder = _Geocoder([GeocoderTimedOut("slow"), _Loc(1.0, 2.0)])

    lat, lon = geocode_address(geocoder, "q", timeout=10, max_retries=2, delay_seconds=1.2)

    assert (lat, lon) == (1.0, 2.0)
    assert len(geocoder.calls) == 2


def test_geocode_address_exhausted_retries_returns_none(monkeypatch):
    monkeypatch.setattr("transform.tripadvisor_clean.geocode.time.sleep", lambda _s: None)
    geocoder = _Geocoder([GeocoderTimedOut("slow"), GeocoderTimedOut("slow")])

    assert geocode_address(geocoder, "q", timeout=10, max_retries=2, delay_seconds=1.2) == (
        None,
        None,
    )


def test_geocode_address_no_match_returns_none(monkeypatch):
    monkeypatch.setattr("transform.tripadvisor_clean.geocode.time.sleep", lambda _s: None)
    geocoder = _Geocoder([None])

    assert geocode_address(geocoder, "nowhere", timeout=10, max_retries=2, delay_seconds=1.2) == (
        None,
        None,
    )


def test_geocode_one_null_address_makes_no_call():
    geocoder = _Geocoder([])  # would IndexError if called
    assert geocode_one(geocoder, {"address": "NaN"}, _settings()) == (None, None)
    assert geocoder.calls == []


def test_build_query_structured_when_parts_present():
    query = build_query(
        {
            "street": "Via Vela",
            "house_number": "14",
            "postal_code": "20133",
            "city": "Milano",
            "address": "Via Vela, 14, 20133 Milano",
        }
    )
    assert query == {
        "country": "Italy",
        "street": "Via Vela, 14",
        "postalcode": "20133",
        "city": "Milano",
    }


def test_build_query_falls_back_to_freetext():
    query = build_query({"street": None, "postal_code": None, "address": "Piazza Duomo, Milano"})
    assert query == "Piazza Duomo, Milano"
