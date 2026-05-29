import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import Settings

_LOG = logging.getLogger(__name__)

NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

NEARBY_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.types",
        "places.primaryType",
        "places.rating",
        "places.userRatingCount",
        "places.addressComponents",
    ]
)
DETAILS_FIELD_MASK = "*"

NEARBY_MAX_RESULTS = 20


class PlacesError(RuntimeError):
    pass


class TransientPlacesError(PlacesError):
    """5xx, 429, or network errors. Retried by the client."""


class PermanentPlacesError(PlacesError):
    """4xx (except 429) and parse errors. Not retried."""


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = [
        (k, v if k != "key" else "***") for k, v in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(parts._replace(query=urlencode(pairs, safe="*")))


class PlacesClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=settings.request_timeout_s)

    @property
    def _api_key(self) -> str:
        return self._settings.google_places_api_key.get_secret_value()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PlacesClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    @retry(
        retry=retry_if_exception_type(TransientPlacesError),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _post(self, url: str, json_body: dict[str, Any], field_mask: str) -> dict[str, Any]:
        return self._send("POST", url, field_mask, json_body=json_body)

    @retry(
        retry=retry_if_exception_type(TransientPlacesError),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _get(self, url: str, field_mask: str) -> dict[str, Any]:
        return self._send("GET", url, field_mask)

    def _send(
        self,
        method: str,
        url: str,
        field_mask: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": field_mask,
            "Content-Type": "application/json",
        }
        try:
            resp = self._client.request(method, url, headers=headers, json=json_body)
        except httpx.RequestError as exc:
            _LOG.warning("network error for %s: %s", redact_url(url), exc)
            raise TransientPlacesError(f"network error: {exc}") from exc

        if resp.status_code == 429 or resp.status_code >= 500:
            retry_after = resp.headers.get("Retry-After")
            _LOG.warning(
                "transient %s on %s (retry-after=%s)",
                resp.status_code,
                redact_url(url),
                retry_after,
            )
            raise TransientPlacesError(f"{resp.status_code} {resp.reason_phrase}")
        if resp.status_code >= 400:
            _LOG.error(
                "permanent %s on %s: %s",
                resp.status_code,
                redact_url(url),
                resp.text[:500],
            )
            raise PermanentPlacesError(
                f"{resp.status_code} {resp.reason_phrase}: {resp.text[:200]}"
            )
        return resp.json()

    def nearby_search(
        self,
        lat: float,
        lon: float,
        radius_m: float,
        included_types: list[str],
        page_token: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "includedTypes": list(included_types),
            "maxResultCount": NEARBY_MAX_RESULTS,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": float(radius_m),
                }
            },
        }
        if page_token:
            body["pageToken"] = page_token
        return self._post(NEARBY_URL, body, NEARBY_FIELD_MASK)

    def place_details(self, place_id: str) -> dict[str, Any]:
        return self._get(DETAILS_URL.format(place_id=place_id), DETAILS_FIELD_MASK)
