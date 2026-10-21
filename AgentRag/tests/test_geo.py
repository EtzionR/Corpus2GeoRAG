"""geo.py: plain-Python geometry, [lon, lat] order."""
import pytest

from geo import bbox, distance_m, in_shape, parse_wkt

SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                                             [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]]}   # with a hole


def test_distance_kyiv_to_kharkiv_is_about_410_km():
    assert distance_m(30.52, 50.45, 36.23, 49.99) == pytest.approx(410_000, rel=0.02)


def test_point_in_polygon_respects_holes():
    assert in_shape(2, 2, SQUARE) and not in_shape(5, 5, SQUARE) and not in_shape(11, 5, SQUARE)


def test_multipolygon():
    shape = {"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"][:1],
                                                     [[[20, 20], [21, 20], [21, 21], [20, 21], [20, 20]]]]}
    assert in_shape(20.5, 20.5, shape) and not in_shape(15, 15, shape)


def test_parse_wkt_types_in_lon_lat_order():
    assert parse_wkt("POINT (30.5 50.4)") == {"type": "Point", "coordinates": [30.5, 50.4]}
    poly = parse_wkt("POLYGON ((30.2 50.3, 30.8 50.3, 30.8 50.6, 30.2 50.3))")
    assert poly["type"] == "Polygon" and poly["coordinates"][0][1] == [30.8, 50.3]
    multi = parse_wkt("MULTIPOLYGON (((0 0, 1 0, 1 1, 0 0)), ((5 5, 6 5, 6 6, 5 5), (5.2 5.2, 5.4 5.2, 5.4 5.4, 5.2 5.2)))")
    assert multi["type"] == "MultiPolygon" and len(multi["coordinates"]) == 2 and len(multi["coordinates"][1]) == 2
    line = parse_wkt("LINESTRING (1 2, 3 4)")
    assert line == {"type": "LineString", "coordinates": [[1, 2], [3, 4]]}
    assert parse_wkt(None) is None and parse_wkt("GARBAGE") is None


def test_bbox():
    assert bbox(SQUARE) == (0, 0, 10, 10)


def test_simplify_caps_the_points_and_keeps_rings_closed():
    import math
    from geo import count_points, simplify
    ring = [[30 + math.cos(i / 500 * 2 * math.pi), 50 + math.sin(i / 500 * 2 * math.pi)] for i in range(500)]
    ring.append(ring[0])
    shape = {"type": "Polygon", "coordinates": [ring]}
    small = simplify(shape, max_points=60)
    assert count_points(small) <= 60 and small["coordinates"][0][0] == small["coordinates"][0][-1]
    assert bbox(small) == pytest.approx(bbox(shape), abs=0.05)          # the outline keeps its extent
    assert simplify({"type": "Point", "coordinates": [1, 2]}) == {"type": "Point", "coordinates": [1, 2]}
    assert simplify(SQUARE, max_points=300) == SQUARE                   # already small: unchanged
