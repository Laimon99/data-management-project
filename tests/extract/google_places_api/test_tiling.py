import math

import pytest

from extract.google_places_api.tiling import generate_multi_centre_tiles, generate_tiles

_M_PER_DEG_LAT = 111_320.0


def test_tiles_nonempty():
    tiles = generate_tiles(45.46, 9.19, outer_radius_m=3000, tile_radius_m=750, overlap=0.3)
    assert len(tiles) > 1


def test_tiles_within_bounds():
    tiles = generate_tiles(45.46, 9.19, outer_radius_m=2000, tile_radius_m=500, overlap=0.3)
    cos_lat = math.cos(math.radians(45.46))
    for t in tiles:
        d_m = math.hypot(
            (t.lat - 45.46) * _M_PER_DEG_LAT,
            (t.lon - 9.19) * _M_PER_DEG_LAT * cos_lat,
        )
        assert d_m <= 2000 + 500 + 1


def test_tiles_overlap_with_neighbours():
    tiles = generate_tiles(45.46, 9.19, outer_radius_m=2000, tile_radius_m=500, overlap=0.3)
    cos_lat = math.cos(math.radians(45.46))
    if len(tiles) < 2:
        pytest.skip("not enough tiles to check overlap")
    overlapping = False
    for i, t1 in enumerate(tiles):
        for j in range(i + 1, len(tiles)):
            t2 = tiles[j]
            d = math.hypot(
                (t1.lat - t2.lat) * _M_PER_DEG_LAT,
                (t1.lon - t2.lon) * _M_PER_DEG_LAT * cos_lat,
            )
            if 0 < d < 2 * 500:
                overlapping = True
                break
        if overlapping:
            break
    assert overlapping


def test_invalid_overlap_raises():
    with pytest.raises(ValueError):
        generate_tiles(45.46, 9.19, 1000, 500, overlap=1.0)


def test_invalid_radius_raises():
    with pytest.raises(ValueError):
        generate_tiles(45.46, 9.19, 0, 500, overlap=0.2)


def test_multi_centre_far_apart_is_union():
    a = (45.46, 9.19, 1000)
    b = (45.60, 9.40, 1000)  # ~20 km away, no overlap
    tiles_a = generate_tiles(*a, tile_radius_m=500, overlap=0.3)
    tiles_b = generate_tiles(*b, tile_radius_m=500, overlap=0.3)
    multi = generate_multi_centre_tiles([a, b], tile_radius_m=500, overlap=0.3)
    assert len(multi) == len(tiles_a) + len(tiles_b)


def test_multi_centre_identical_anchors_dedupes_fully():
    a = (45.46, 9.19, 1000)
    single = generate_tiles(*a, tile_radius_m=500, overlap=0.3)
    multi = generate_multi_centre_tiles([a, a], tile_radius_m=500, overlap=0.3)
    assert len(multi) == len(single)


def test_multi_centre_partial_overlap_fewer_than_sum():
    a = (45.46, 9.19, 1000)
    b = (45.465, 9.196, 1000)  # ~700 m away, grids overlap
    tiles_a = generate_tiles(*a, tile_radius_m=500, overlap=0.3)
    tiles_b = generate_tiles(*b, tile_radius_m=500, overlap=0.3)
    multi = generate_multi_centre_tiles([a, b], tile_radius_m=500, overlap=0.3)
    assert len(multi) < len(tiles_a) + len(tiles_b)


def test_multi_centre_order_independent():
    a = (45.46, 9.19, 1000)
    b = (45.465, 9.196, 1000)
    ab = generate_multi_centre_tiles([a, b], tile_radius_m=500, overlap=0.3)
    ba = generate_multi_centre_tiles([b, a], tile_radius_m=500, overlap=0.3)
    assert len(ab) == len(ba)


def test_multi_centre_preserves_tile_radius():
    multi = generate_multi_centre_tiles([(45.46, 9.19, 1000)], tile_radius_m=500, overlap=0.3)
    assert all(t.radius_m == 500 for t in multi)


def test_multi_centre_empty_centres():
    assert generate_multi_centre_tiles([], tile_radius_m=500, overlap=0.3) == []
