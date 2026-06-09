from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

from .preprocess import normalize_name

# Curated from repeated Google anchor names in the Milan data. Generic repeated names
# such as "bar", "pizzeria", "bar centrale", and "panificio" are intentionally excluded.
CURATED_CHAIN_BRANDS: frozenset[str] = frozenset(
    {
        "12oz",
        "alice pizza",
        "autogrill",
        "bar atlantic",
        "burger king",
        "burgez",
        "caffe vergnano",
        "california bakery",
        "cioccolatitaliani",
        "five guys",
        "flower burger",
        "fratelli la bufala",
        "i love poke",
        "kfc",
        "la piadineria",
        "marchesi 1824",
        "mcdonald s",
        "mcdonalds",
        "miscusi",
        "old wild west",
        "panificio davide longoni",
        "panino giusto",
        "poke house",
        "popeyes famous louisiana chicken",
        "roadhouse",
        "rossopomodoro",
        "signorvino",
        "spontini",
        "spun tiramisu",
        "starbucks",
        "street smash burgers",
        "verocaffe",
    }
)


@dataclass(frozen=True)
class ChainInfo:
    is_chain: bool
    brand: str | None = None
    google_brand: str | None = None
    source_brand: str | None = None


def normalize_chain_name(value: Any) -> str:
    normalized = normalize_name(value)
    without_accents = unicodedata.normalize("NFKD", normalized)
    return "".join(char for char in without_accents if not unicodedata.combining(char))


def chain_brand_for_name(value: Any) -> str | None:
    normalized = normalize_chain_name(value)
    if not normalized:
        return None
    for brand in sorted(CURATED_CHAIN_BRANDS, key=len, reverse=True):
        if normalized == brand or normalized.startswith(f"{brand} "):
            return brand
    return None


def chain_info_for_pair(
    google_doc: dict[str, Any],
    source_doc: dict[str, Any],
) -> ChainInfo:
    google_brand = chain_brand_for_name(google_doc.get("name"))
    source_brand = chain_brand_for_name(source_doc.get("restaurant_name") or source_doc.get("name"))
    brands = [brand for brand in (google_brand, source_brand) if brand is not None]
    if not brands:
        return ChainInfo(is_chain=False)
    brand = brands[0] if len(set(brands)) == 1 else "|".join(brands)
    return ChainInfo(
        is_chain=True,
        brand=brand,
        google_brand=google_brand,
        source_brand=source_brand,
    )
