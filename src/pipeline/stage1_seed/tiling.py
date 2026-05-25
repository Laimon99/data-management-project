import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Tile:
    lat: float
    lon: float
    radius_m: int


_M_PER_DEG_LAT = 111_320.0


def generate_tiles(
    center_lat: float,
    center_lon: float,
    outer_radius_m: float,
    tile_radius_m: float,
    overlap: float = 0.2,
) -> list[Tile]:
    """Square offset grid of overlapping circles covering an outer circle.

    `overlap` is the fraction by which neighbouring tile centres are pulled
    closer than 2*tile_radius_m, producing overlap between adjacent disks.
    """
    if not 0 <= overlap < 1:
        raise ValueError("overlap must be in [0, 1)")
    if tile_radius_m <= 0 or outer_radius_m <= 0:
        raise ValueError("radii must be positive")

    step_m = 2 * tile_radius_m * (1 - overlap)
    n = int(math.ceil(outer_radius_m / step_m)) + 1

    cos_lat = math.cos(math.radians(center_lat))
    m_per_deg_lon = _M_PER_DEG_LAT * cos_lat

    tiles: list[Tile] = []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            dx_m = i * step_m
            dy_m = j * step_m
            if math.hypot(dx_m, dy_m) > outer_radius_m + tile_radius_m:
                continue
            lat = center_lat + (dy_m / _M_PER_DEG_LAT)
            lon = center_lon + (dx_m / m_per_deg_lon)
            tiles.append(Tile(lat=lat, lon=lon, radius_m=int(tile_radius_m)))
    return tiles


def generate_multi_centre_tiles(
    centres: list[tuple[float, float, float]],
    tile_radius_m: float,
    overlap: float = 0.2,
) -> list[Tile]:
    """Union of per-centre tile grids, deduplicated on a shared step-grid.

    Each centre is `(lat, lon, outer_radius_m)`. Tile centres are snapped to one
    global metre-based grid (cell size = the generator's `step_m`); one tile is
    kept per occupied cell, so the same area is never queried twice and the
    result is independent of anchor order.
    """
    step_m = 2 * tile_radius_m * (1 - overlap)
    ref_lat = centres[0][0] if centres else 0.0
    m_per_deg_lon = _M_PER_DEG_LAT * math.cos(math.radians(ref_lat))

    kept: list[Tile] = []
    seen_cells: set[tuple[int, int]] = set()
    for lat, lon, outer in centres:
        for t in generate_tiles(lat, lon, outer, tile_radius_m, overlap):
            cell = (
                round((t.lat * _M_PER_DEG_LAT) / step_m),
                round((t.lon * m_per_deg_lon) / step_m),
            )
            if cell in seen_cells:
                continue
            seen_cells.add(cell)
            kept.append(t)
    return kept
