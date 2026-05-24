import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .checkpoint import TileCheckpoint
from .config import Settings
from .places_client import PermanentPlacesError, PlacesClient, TransientPlacesError
from .schema import from_nearby_place
from .storage import SeedStore
from .tiling import generate_tiles

_LOG = logging.getLogger(__name__)


@dataclass
class ListReport:
    tiles_processed: int = 0
    tiles_skipped: int = 0
    places_seen: int = 0
    unique_places: int = 0
    pages_fetched: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


def run_mode_list(
    settings: Settings,
    store: SeedStore,
    client: PlacesClient,
    ckpt: TileCheckpoint,
    *,
    max_results: int | None = None,
) -> ListReport:
    tiles = generate_tiles(
        center_lat=settings.milan_center_lat,
        center_lon=settings.milan_center_lon,
        outer_radius_m=settings.outer_radius_m,
        tile_radius_m=settings.search_radius_m,
        overlap=settings.tile_overlap,
    )
    report = ListReport()
    seen_ids: set[str] = set()

    for tile in tiles:
        if ckpt.has(tile):
            report.tiles_skipped += 1
            continue
        try:
            page_token: str | None = None
            for _ in range(settings.max_pages_per_tile):
                resp = client.nearby_search(
                    lat=tile.lat,
                    lon=tile.lon,
                    radius_m=tile.radius_m,
                    included_types=settings.included_types,
                    page_token=page_token,
                )
                report.pages_fetched += 1
                for place in resp.get("places") or []:
                    try:
                        doc = from_nearby_place(place)
                    except ValueError as exc:
                        report.errors.append({"place": place.get("id"), "reason": str(exc)})
                        continue
                    report.places_seen += 1
                    seen_ids.add(doc.place_id)
                    store.upsert(doc)
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
            ckpt.add(tile)
            report.tiles_processed += 1
            if settings.request_delay_s > 0:
                time.sleep(settings.request_delay_s)
            if max_results is not None and len(seen_ids) >= max_results:
                _LOG.info("reached max_results=%d, stopping early", max_results)
                break
        except (TransientPlacesError, PermanentPlacesError) as exc:
            report.errors.append(
                {
                    "tile": [tile.lat, tile.lon, tile.radius_m],
                    "reason": str(exc),
                }
            )
            _LOG.warning("tile %s,%s failed after retries: %s", tile.lat, tile.lon, exc)

    report.unique_places = len(seen_ids)
    return report
