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
