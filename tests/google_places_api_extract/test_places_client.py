import logging

import httpx
import pytest
import respx
from google_places_api_extract.logging_setup import APIKeyRedactingFilter
from google_places_api_extract.places_client import (
    NEARBY_URL,
    PermanentPlacesError,
    PlacesClient,
    TransientPlacesError,
    redact_url,
)


def test_nearby_search_happy_path(settings):
    with respx.mock() as router:
        route = router.post(NEARBY_URL).respond(200, json={"places": []})
        with PlacesClient(settings) as client:
            resp = client.nearby_search(45.46, 9.19, 750, ["restaurant"])
        assert resp == {"places": []}
        assert route.calls[0].request.headers.get("X-Goog-Api-Key") == "test-key-xyz"
        assert route.calls[0].request.headers.get("X-Goog-FieldMask")


def test_429_is_retried(settings, fast_retries):
    with respx.mock() as router:
        route = router.post(NEARBY_URL).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "1"}, json={}),
                httpx.Response(200, json={"places": []}),
            ]
        )
        with PlacesClient(settings) as client:
            resp = client.nearby_search(45.46, 9.19, 750, ["restaurant"])
        assert resp == {"places": []}
        assert route.call_count == 2


def test_persistent_5xx_raises_transient(settings, fast_retries):
    with respx.mock() as router:
        route = router.post(NEARBY_URL).respond(503, json={})
        with PlacesClient(settings) as client:
            with pytest.raises(TransientPlacesError):
                client.nearby_search(45.46, 9.19, 750, ["restaurant"])
        assert route.call_count == 5  # stop_after_attempt(5)


def test_4xx_permanent_not_retried(settings, fast_retries):
    with respx.mock() as router:
        route = router.post(NEARBY_URL).respond(400, json={"error": {"message": "bad"}})
        with PlacesClient(settings) as client:
            with pytest.raises(PermanentPlacesError):
                client.nearby_search(45.46, 9.19, 750, ["restaurant"])
        assert route.call_count == 1


def test_redact_url_strips_key():
    url = "https://example.com/foo?key=secret123&q=x"
    redacted = redact_url(url)
    assert "secret123" not in redacted
    assert "***" in redacted
    assert "q=x" in redacted


def test_redact_url_no_query():
    url = "https://example.com/foo"
    assert redact_url(url) == url


def test_apikey_redacting_filter_scrubs_msg():
    f = APIKeyRedactingFilter("secret123")
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="something key=secret123 here",
        args=None,
        exc_info=None,
    )
    f.filter(record)
    assert record.msg == "something key=*** here"


def test_apikey_redacting_filter_scrubs_args():
    f = APIKeyRedactingFilter("secret123")
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="url=%s",
        args=("https://x?key=secret123",),
        exc_info=None,
    )
    f.filter(record)
    assert "secret123" not in record.getMessage()
    assert "***" in record.getMessage()
