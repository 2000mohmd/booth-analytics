"""Sanity check that booth.example.yaml parses and has the fields every downstream service assumes."""
from pathlib import Path

import yaml

CONFIG = Path(__file__).parent.parent.parent / "configs" / "booth.example.yaml"


def test_booth_config_loads_expected_keys():
    cfg = yaml.safe_load(CONFIG.read_text())
    assert cfg["booth_id"]
    assert len(cfg["cameras"]) >= 1
    assert set(cfg["zones"].keys()) >= {"aisle", "stand", "table"}
    assert cfg["thresholds"]["dwell_seconds_stopper"] > 0
