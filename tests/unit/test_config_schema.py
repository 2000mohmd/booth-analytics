"""Sanity check that booth.example.yaml parses and has the fields every downstream service assumes."""
from pathlib import Path

import yaml

CONFIG = Path(__file__).parent.parent.parent / "configs" / "booth.example.yaml"


def test_booth_config_loads_expected_keys():
    cfg = yaml.safe_load(CONFIG.read_text())
    assert cfg["booth_id"]

    overhead = [c for c in cfg["cameras"] if c["role"] == "overhead"]
    assert len(overhead) >= 1
    zone_names = {name for cam in overhead for name in cam.get("zones", {})}
    assert zone_names >= {"aisle", "stand", "table"}  # union across cameras, not per-camera

    assert cfg["thresholds"]["dwell_seconds_stopper"] > 0
