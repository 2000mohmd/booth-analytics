from services.metrics_engine.zones import ZoneMap

ZONES = {
    "aisle": [[0, 0], [100, 0], [100, 20], [0, 20]],
    "stand": [[0, 20], [100, 20], [100, 80], [0, 80]],
}


def test_point_in_aisle():
    zm = ZoneMap(ZONES)
    assert zm.zone_for_point(50, 10) == "aisle"


def test_point_in_stand():
    zm = ZoneMap(ZONES)
    assert zm.zone_for_point(50, 50) == "stand"


def test_point_outside_any_zone():
    zm = ZoneMap(ZONES)
    assert zm.zone_for_point(500, 500) is None


def test_undersized_polygon_ignored():
    zm = ZoneMap({"degenerate": [[0, 0], [1, 1]]})
    assert zm.zone_for_point(0, 0) is None


def test_point_on_zone_boundary_counts_as_inside():
    """A point exactly on a polygon's edge/vertex fails shapely's contains() (interior-only) but
    passes touches() - zone_for_point() checks both so booth-edge visitors aren't dropped."""
    zm = ZoneMap(ZONES)
    assert zm.zone_for_point(0, 0) == "aisle"       # a corner vertex
    assert zm.zone_for_point(50, 0) == "aisle"      # midpoint of an edge


def test_empty_zone_map_never_matches():
    zm = ZoneMap({})
    assert zm.zone_for_point(0, 0) is None


def test_triangle_is_a_valid_zone():
    zm = ZoneMap({"tri": [[0, 0], [10, 0], [5, 10]]})
    assert zm.zone_for_point(5, 3) == "tri"


def test_overlapping_zones_first_declared_wins():
    """Iteration order over self.polygons follows dict insertion order, so when two zones
    overlap the one declared first in the config takes precedence."""
    zm = ZoneMap({
        "outer": [[0, 0], [100, 0], [100, 100], [0, 100]],
        "inner": [[10, 10], [90, 10], [90, 90], [10, 90]],
    })
    assert zm.zone_for_point(50, 50) == "outer"
