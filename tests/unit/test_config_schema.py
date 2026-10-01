"""Sanity check that booth.example.yaml parses and has the fields every downstream service assumes."""
from pathlib import Path

import yaml

from services.ingestion.main import parse_zone_transitions

CONFIG = Path(__file__).parent.parent.parent / "configs" / "booth.example.yaml"


def test_booth_config_loads_expected_keys():
    cfg = yaml.safe_load(CONFIG.read_text())
    assert cfg["booth_id"]

    overhead = [c for c in cfg["cameras"] if c["role"] == "overhead"]
    assert len(overhead) >= 1
    zone_names = {name for cam in overhead for name in cam.get("zones", {})}
    assert zone_names >= {"aisle", "stand", "table"}  # union across cameras, not per-camera

    assert cfg["thresholds"]["dwell_seconds_stopper"] > 0


def test_zone_transitions_reference_real_cameras_and_zones():
    cfg = yaml.safe_load(CONFIG.read_text())
    cameras = {cam["id"]: set(cam.get("zones", {})) for cam in cfg["cameras"]}

    transitions = parse_zone_transitions(cfg.get("zone_transitions"))
    assert len(transitions) > 0  # the example ships at least one, to illustrate the shape

    for (from_cam, from_zone), (to_cam, to_zone), max_gap in transitions:
        assert from_zone in cameras[from_cam]
        assert to_zone in cameras[to_cam]
        assert max_gap > 0
