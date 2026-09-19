import pytest

from services.metrics_engine import store
from services.metrics_engine.occupancy import build_daily_summary


@pytest.fixture
def conn(tmp_path):
    return store.connect(tmp_path / "events.db")


def _visit(visit_id, hour, is_stopper, dwell, gender, age, is_staff=False):
    return {
        "visit_id": visit_id, "booth_id": "booth-01",
        "entered_at": f"2026-09-19T{hour:02d}:00:00+00:00",
        "exited_at": f"2026-09-19T{hour:02d}:00:{int(dwell):02d}+00:00",
        "zone_path": "aisle", "dwell_seconds": dwell, "is_stopper": is_stopper,
        "is_staff": is_staff, "gender_est": gender, "gender_conf": 0.9,
        "age_bracket": age, "age_conf": 0.9, "position_trace": "",
    }


def test_daily_summary_math(conn):
    store.insert_visit(conn, _visit("v1", 10, True, 8.0, "female", "18-35"))
    store.insert_visit(conn, _visit("v2", 10, True, 12.0, "male", "18-35"))
    store.insert_visit(conn, _visit("v3", 14, False, 1.0, "unknown", "unknown"))
    store.insert_visit(conn, _visit("staff1", 10, True, 100.0, None, None, is_staff=True))

    summary = build_daily_summary(conn, "booth-01", "2026-09-19")

    assert summary["passersby"] == 3          # staff excluded
    assert summary["stoppers"] == 2
    assert summary["capture_rate"] == round(2 / 3, 3)
    assert summary["avg_dwell"] == 10.0
    assert summary["gender_split"] == {"female": 0.5, "male": 0.5}
    assert summary["peak_hour"] == "10"


def test_empty_day_is_zeroed_not_crashed(conn):
    summary = build_daily_summary(conn, "booth-01", "2026-01-01")
    assert summary["passersby"] == 0
    assert summary["capture_rate"] == 0.0
    assert summary["gender_split"] == {}
