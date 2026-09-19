"""Polygon-in/out zone tests. Zone order in config (aisle -> stand -> table) defines the funnel."""
from shapely.geometry import Point, Polygon


class ZoneMap:
    def __init__(self, zones: dict[str, list[list[float]]]):
        self.polygons = {name: Polygon(pts) for name, pts in zones.items() if len(pts) >= 3}

    def zone_for_point(self, x: float, y: float) -> str | None:
        p = Point(x, y)
        for name, poly in self.polygons.items():
            if poly.contains(p) or poly.touches(p):
                return name
        return None
