from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class SeedDoc(BaseModel):
    place_id: str
    name: str
    formatted_address: str | None = None
    city: str = "Milan"
    latitude: float
    longitude: float
    types: list[str] = Field(default_factory=list)
    primary_type: str | None = None
    rating: float | None = None
    user_rating_count: int | None = None
    details: dict[str, Any] | None = None
    details_fetched_at: datetime | None = None
    seed_collected_at: datetime = Field(default_factory=_utcnow)


_LOCALITY_TYPES = frozenset({"locality", "postal_town", "administrative_area_level_3"})


def _extract_city(place: dict[str, Any]) -> str:
    components = place.get("addressComponents") or []
    for comp in components:
        types = set(comp.get("types") or [])
        if types & _LOCALITY_TYPES:
            text = comp.get("longText") or comp.get("shortText")
            if text:
                return text
    return "Milan"


def from_nearby_place(place: dict[str, Any]) -> SeedDoc:
    place_id = place.get("id")
    if not place_id:
        raise ValueError("place missing 'id'")
    display = place.get("displayName") or {}
    name = display.get("text") or place_id
    location = place.get("location") or {}
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if latitude is None or longitude is None:
        raise ValueError(f"place {place_id} missing location")
    return SeedDoc(
        place_id=place_id,
        name=name,
        formatted_address=place.get("formattedAddress"),
        city=_extract_city(place),
        latitude=float(latitude),
        longitude=float(longitude),
        types=list(place.get("types") or []),
        primary_type=place.get("primaryType"),
        rating=place.get("rating"),
        user_rating_count=place.get("userRatingCount"),
    )


def merge_details(doc: SeedDoc, raw_details: dict[str, Any]) -> SeedDoc:
    """Return a copy of `doc` with detail fields updated; seed fields preserved."""
    update: dict[str, Any] = {
        "details": raw_details,
        "details_fetched_at": _utcnow(),
    }
    if (rating := raw_details.get("rating")) is not None:
        update["rating"] = rating
    if (count := raw_details.get("userRatingCount")) is not None:
        update["user_rating_count"] = count
    if not doc.formatted_address and (addr := raw_details.get("formattedAddress")):
        update["formatted_address"] = addr
    return doc.model_copy(update=update)
