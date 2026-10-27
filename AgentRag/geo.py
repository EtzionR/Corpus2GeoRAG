"""Plain-Python geometry, so nothing needs shapely (blocked by Windows Smart App Control on at least
one team machine, DECISIONS_LOG P2-6). Coordinates are [lon, lat] (GeoJSON order) everywhere.
"""
import math
import re
from typing import Optional

EARTH_RADIUS_M = 6_371_000


def distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle (haversine) distance in metres."""
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _in_ring(lon: float, lat: float, ring: list) -> bool:
    """Ray casting: is the point inside one closed ring of [lon, lat] positions?"""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def in_polygon(lon: float, lat: float, rings: list) -> bool:
    """GeoJSON polygon rings: inside the outer ring and outside every hole."""
    return bool(rings) and _in_ring(lon, lat, rings[0]) and not any(_in_ring(lon, lat, h) for h in rings[1:])


def in_shape(lon: float, lat: float, shape: dict) -> bool:
    """A GeoJSON-style {"type": "Polygon"|"MultiPolygon", "coordinates": ...}."""
    if shape["type"] == "Polygon":
        return in_polygon(lon, lat, shape["coordinates"])
    if shape["type"] == "MultiPolygon":
        return any(in_polygon(lon, lat, rings) for rings in shape["coordinates"])
    return False


def bbox(shape: dict) -> tuple[float, float, float, float]:
    """(west, south, east, north) of any GeoJSON-style geometry."""
    xs, ys = [], []

    def walk(c):
        if c and isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for x in c:
                walk(x)
    walk(shape["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def _perpendicular(p, a, b) -> float:
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return math.hypot(x - x1, y - y1)
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def _douglas_peucker(points: list, tolerance: float) -> list:
    """Keeps the shape's corners, drops points closer than `tolerance` to the line between kept ones."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        best, index = 0.0, None
        for i in range(start + 1, end):
            d = _perpendicular(points[i], points[start], points[end])
            if d > best:
                best, index = d, i
        if index is not None and best > tolerance:
            keep[index] = True
            stack += [(start, index), (index, end)]
    return [p for p, k in zip(points, keep) if k]


def _rings(shape: dict) -> list:
    if shape["type"] == "Polygon":
        return shape["coordinates"]
    if shape["type"] == "MultiPolygon":
        return [r for poly in shape["coordinates"] for r in poly]
    if shape["type"] == "LineString":
        return [shape["coordinates"]]
    if shape["type"] == "MultiLineString":
        return shape["coordinates"]
    return []


def count_points(shape: dict) -> int:
    return sum(len(r) for r in _rings(shape))


def simplify(shape: Optional[dict], max_points: int = 300) -> Optional[dict]:
    """Simplify a GeoJSON polygon or line until it has at most `max_points` points in total, so a
    state's 150,000-character outline becomes something a map can draw at once. Rings that shrink
    below a valid polygon are dropped; points and small shapes are returned unchanged."""
    if not shape or shape["type"] == "Point" or count_points(shape) <= max_points:
        return shape
    w, s, e, n = bbox(shape)
    tolerance = max(e - w, n - s) / 2000
    is_line = shape["type"] in ("LineString", "MultiLineString")
    minimum = 2 if is_line else 4

    def ring(r):
        out = _douglas_peucker(r, tolerance)
        if not is_line and out[0] != out[-1]:
            out.append(out[0])
        return out if len(out) >= minimum else None

    for _ in range(20):
        if shape["type"] == "Polygon":
            rings = [x for x in (ring(r) for r in shape["coordinates"]) if x]
            out = {"type": "Polygon", "coordinates": rings} if rings else None
        elif shape["type"] == "MultiPolygon":
            polys = [[x for x in (ring(r) for r in poly) if x] for poly in shape["coordinates"]]
            polys = [p for p in polys if p]
            out = {"type": "MultiPolygon", "coordinates": polys} if polys else None
        elif shape["type"] == "LineString":
            out = {"type": "LineString", "coordinates": ring(shape["coordinates"]) or shape["coordinates"][:2]}
        else:
            lines = [x for x in (ring(r) for r in shape["coordinates"]) if x]
            out = {"type": "MultiLineString", "coordinates": lines} if lines else None
        if out and count_points(out) <= max_points:
            return out
        tolerance *= 2
    return out


_NUMBERS = re.compile(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?")


def _positions(text: str) -> list:
    nums = [float(x) for x in _NUMBERS.findall(text)]
    return [[nums[i], nums[i + 1]] for i in range(0, len(nums) - 1, 2)]


def _groups(text: str) -> list[str]:
    """The top-level parenthesized groups of a WKT body: '(a), (b)' -> ['a', 'b']."""
    out, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "(":
            if depth == 0:
                start = i + 1
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                out.append(text[start:i])
    return out


def parse_wkt(wkt: Optional[str]) -> Optional[dict]:
    """WKT (the graph's geometry_wkt, 'lon lat' order) -> a GeoJSON geometry dict, or None."""
    if not wkt:
        return None
    m = re.match(r"\s*(\w+)\s*\((.*)\)\s*$", wkt, re.S)
    if not m:
        return None
    kind, body = m.group(1).upper(), m.group(2)
    if kind == "POINT":
        return {"type": "Point", "coordinates": _positions(body)[0]}
    if kind == "LINESTRING":
        return {"type": "LineString", "coordinates": _positions(body)}
    if kind == "MULTILINESTRING":
        return {"type": "MultiLineString", "coordinates": [_positions(g) for g in _groups(body)]}
    if kind == "POLYGON":
        return {"type": "Polygon", "coordinates": [_positions(g) for g in _groups(body)]}
    if kind == "MULTIPOLYGON":
        return {"type": "MultiPolygon", "coordinates": [[_positions(r) for r in _groups(p)] for p in _groups(body)]}
    return None
