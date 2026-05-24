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
