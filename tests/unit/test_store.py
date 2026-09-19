import json

import pytest

from services.metrics_engine import store


@pytest.fixture
def conn(tmp_path):
    return store.connect(tmp_path / "events.db")


def _visit(visit_id="v1", **overrides):
    row = {
        "visit_id": visit_id, "booth_id": "booth-01", "entered_at": "2026-09-19T10:00:00+00:00",
        "exited_at": "2026-09-19T10:00:05+00:00", "zone_path": "aisle→stand", "dwell_seconds": 5.0,
        "is_stopper": True, "is_staff": False, "gender_est": None, "gender_conf": None,
        "age_bracket": None, "age_conf": None, "position_trace": "10,10;20,20",
    }
    row.update(overrides)
    return row


def test_insert_and_read_visit(conn):
    store.insert_visit(conn, _visit())
    row = conn.execute("SELECT * FROM visits WHERE visit_id='v1'").fetchone()
    assert row["dwell_seconds"] == 5.0
    assert row["is_stopper"] == 1


def test_update_visit_demographics(conn):
    store.insert_visit(conn, _visit())
    store.update_visit_demographics(conn, "v1", "female", 0.9, "18-35", 0.8)
    row = conn.execute("SELECT * FROM visits WHERE visit_id='v1'").fetchone()
    assert row["gender_est"] == "female"
    assert row["age_bracket"] == "18-35"


def test_occupancy_sample_roundtrip(conn):
    store.insert_occupancy_sample(conn, "2026-09-19T10:00:00+00:00", "booth-01", 3, 1)
    row = conn.execute("SELECT * FROM occupancy_samples").fetchone()
    assert row["current_count"] == 3
    assert row["staff_count"] == 1


def test_alert_open_and_resolve(conn):
    store.open_alert(conn, "a1", "booth-01", "2026-09-19T10:00:00+00:00", "capacity", "over limit")
    assert len(store.active_alerts(conn, "booth-01")) == 1
    store.resolve_alert(conn, "a1", "2026-09-19T10:05:00+00:00")
    assert len(store.active_alerts(conn, "booth-01")) == 0


def test_daily_summary_upsert_serializes_splits(conn):
    store.upsert_daily_summary(conn, {
        "booth_id": "booth-01", "day": "2026-09-19", "passersby": 10, "stoppers": 4,
        "capture_rate": 0.4, "avg_dwell": 12.5, "median_dwell": 10.0,
        "gender_split": {"male": 0.5, "female": 0.5}, "age_split": {"18-35": 1.0}, "peak_hour": "14",
    })
    row = conn.execute("SELECT * FROM daily_summary").fetchone()
    assert json.loads(row["gender_split"]) == {"male": 0.5, "female": 0.5}
