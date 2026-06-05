from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Format = Literal["jsonl", "json_array"]


@dataclass(frozen=True)
class SourceSpec:
    """Describes how to load one raw source into MongoDB.

    The only real differences between sources are data, not code: the file on
    disk, its format, the natural key that becomes the Mongo ``_id``, and the
    destination collection.
    """

    name: str
    raw_file: Path
    fmt: Format
    key_field: str
    collection: str


SOURCES: dict[str, SourceSpec] = {
    "google": SourceSpec(
        name="google",
        raw_file=Path("data/raw/google_places/restaurants_seed.jsonl"),
        fmt="jsonl",
        key_field="place_id",
        collection="restaurants_raw_google",
    ),
    "tripadvisor": SourceSpec(
        name="tripadvisor",
        raw_file=Path("data/raw/tripadvisor/tripadvisor_scraper_results.json"),
        fmt="json_array",
        key_field="source_url",
        collection="restaurants_raw_tripadvisor",
    ),
    "thefork": SourceSpec(
        name="thefork",
        raw_file=Path("data/raw/thefork/thefork_milan_restaurants_enriched.json"),
        fmt="json_array",
        key_field="source_id",
        collection="restaurants_raw_thefork",
    ),
}


def resolve(selector: str) -> list[SourceSpec]:
    """Map a CLI selector to one or more source specs.

    ``"all"`` expands to every registered source. An unknown selector raises
    ``ValueError`` listing the valid choices.
    """

    if selector == "all":
        return list(SOURCES.values())
    if selector in SOURCES:
        return [SOURCES[selector]]
    valid = ", ".join([*SOURCES.keys(), "all"])
    raise ValueError(f"Unknown source '{selector}'. Valid choices: {valid}.")
