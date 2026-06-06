from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class RestaurantRecord:
    source: str = "thefork"
    source_id: str | None = None
    restaurant_name: str | None = None
    address: str | None = None
    city: str = "Milan"
    latitude: float | None = None
    longitude: float | None = None
    rating: float | None = None
    review_count: int | None = None
    cuisine_type: str | None = None
    price_range: str | None = None
    discount: str | None = None
    photo_count: int | None = None
    website: str | None = None
    social_links: dict[str, str] = field(default_factory=dict)
    phone_number: str | None = None
    email: str | None = None
    working_days_hours: str | None = None
    working_hours_structured: list[Any] = field(default_factory=list)
    restaurant_url: str | None = None
    review_snippets: list[str] = field(default_factory=list)
    reviews: list[Any] = field(default_factory=list)
    scraped_at: str | None = None
    source_page_number: int = 0
    detail_scraped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
