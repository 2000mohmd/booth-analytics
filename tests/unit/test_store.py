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


def test_daily_summary_upsert_overwrites_same_day(conn):
    """(booth_id, day) is the primary key - a re-run of the rollup for a day already stored
    must replace it in place, not create a second row."""
    store.upsert_daily_summary(conn, {
        "booth_id": "booth-01", "day": "2026-09-19", "passersby": 10, "stoppers": 4,
        "capture_rate": 0.4, "avg_dwell": 12.5, "median_dwell": 10.0,
        "gender_split": {}, "age_split": {}, "peak_hour": "14",
    })
    store.upsert_daily_summary(conn, {
        "booth_id": "booth-01", "day": "2026-09-19", "passersby": 20, "stoppers": 8,
        "capture_rate": 0.4, "avg_dwell": 15.0, "median_dwell": 12.0,
        "gender_split": {}, "age_split": {}, "peak_hour": "15",
    })
    rows = conn.execute("SELECT * FROM daily_summary").fetchall()
    assert len(rows) == 1
    assert rows[0]["passersby"] == 20
    assert rows[0]["peak_hour"] == "15"


def test_finalize_visit_updates_lifecycle_fields_but_leaves_demographics_alone(conn):
    store.insert_visit(conn, _visit())
    store.update_visit_demographics(conn, "v1", "female", 0.9, "18-35", 0.8)

    store.finalize_visit(conn, {
        "visit_id": "v1", "exited_at": "2026-09-19T10:00:20+00:00", "zone_path": "aisle→stand→aisle",
        "dwell_seconds": 20.0, "is_stopper": True, "is_staff": False, "position_trace": "1,1",
    })

    row = conn.execute("SELECT * FROM visits WHERE visit_id='v1'").fetchone()
    assert row["exited_at"] == "2026-09-19T10:00:20+00:00"
    assert row["dwell_seconds"] == 20.0
    assert row["gender_est"] == "female"  # untouched by finalize_visit
    assert row["age_bracket"] == "18-35"


def test_insert_visit_replace_overwrites_prior_demographics(conn):
    """insert_visit is INSERT OR REPLACE on the full row - the docstring warns never to call it
    on an in-progress visit that already has demographics attached, because it wipes them."""
    store.insert_visit(conn, _visit())
    store.update_visit_demographics(conn, "v1", "female", 0.9, "18-35", 0.8)

    store.insert_visit(conn, _visit())  # re-insert the original row shape, no demographics

    row = conn.execute("SELECT * FROM visits WHERE visit_id='v1'").fetchone()
    assert row["gender_est"] is None


def test_active_alerts_filters_by_booth_and_orders_newest_first(conn):
    store.open_alert(conn, "a1", "booth-01", "2026-09-19T10:00:00+00:00", "capacity", "d1")
    store.open_alert(conn, "a2", "booth-01", "2026-09-19T10:05:00+00:00", "no_coverage", "d2")
    store.open_alert(conn, "a3", "booth-02", "2026-09-19T10:10:00+00:00", "capacity", "d3")

    active = store.active_alerts(conn, "booth-01")
    assert [a["alert_id"] for a in active] == ["a2", "a1"]


def test_resolved_alert_excluded_from_other_booths_view(conn):
    store.open_alert(conn, "a1", "booth-01", "2026-09-19T10:00:00+00:00", "capacity", "d1")
    store.resolve_alert(conn, "a1", "2026-09-19T10:05:00+00:00")
    assert store.active_alerts(conn, "booth-01") == []
    assert store.active_alerts(conn, "booth-02") == []
