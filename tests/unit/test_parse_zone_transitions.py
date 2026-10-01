from services.ingestion.main import parse_zone_transitions


def test_parses_booth_yaml_shape_into_tuples():
    raw = [
        {"from": {"camera": "cam_a", "zone": "stand"}, "to": {"camera": "cam_b", "zone": "stand"},
         "max_gap_seconds": 2.5},
    ]
    assert parse_zone_transitions(raw) == [(("cam_a", "stand"), ("cam_b", "stand"), 2.5)]


def test_empty_or_missing_config_yields_no_transitions():
    assert parse_zone_transitions(None) == []
    assert parse_zone_transitions([]) == []
