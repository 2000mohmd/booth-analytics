import pytest

from services.metrics_engine import store
from services.metrics_engine.dwell import VisitTracker
from services.metrics_engine.occupancy import build_daily_summary, sample_occupancy


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


def test_daily_summary_ignores_other_booths(conn):
    store.insert_visit(conn, _visit("v1", 10, True, 8.0, "female", "18-35"))
    store.insert_visit(conn, {**_visit("v2", 10, True, 8.0, "male", "18-35"), "booth_id": "booth-02"})

    summary = build_daily_summary(conn, "booth-01", "2026-09-19")
    assert summary["passersby"] == 1


def test_daily_summary_ignores_other_days(conn):
    store.insert_visit(conn, _visit("v1", 10, True, 8.0, "female", "18-35"))

    summary = build_daily_summary(conn, "booth-01", "2026-09-20")
    assert summary["passersby"] == 0


def test_daily_summary_skips_null_dwell_on_a_stopper_row(conn):
    """is_stopper and dwell_seconds are set together by VisitTracker.finalize(), but a
    hand-inserted or partially-written row could have is_stopper=True with a NULL dwell -
    statistics.mean() must not choke on that instead of averaging the non-null dwells."""
    store.insert_visit(conn, _visit("v1", 10, True, 8.0, "female", "18-35"))
    null_dwell_row = {**_visit("v2", 10, True, 0.0, "male", "18-35"), "dwell_seconds": None}
    store.insert_visit(conn, null_dwell_row)

    summary = build_daily_summary(conn, "booth-01", "2026-09-19")
    assert summary["stoppers"] == 2
    assert summary["avg_dwell"] == 8.0


def test_daily_summary_age_split_computed_like_gender_split(conn):
    store.insert_visit(conn, _visit("v1", 10, True, 8.0, "female", "18-35"))
    store.insert_visit(conn, _visit("v2", 10, True, 8.0, "male", "36-50"))

    summary = build_daily_summary(conn, "booth-01", "2026-09-19")
    assert summary["age_split"] == {"18-35": 0.5, "36-50": 0.5}


def test_peak_hour_reflects_the_busiest_hour(conn):
    store.insert_visit(conn, _visit("v1", 9, False, 0.0, None, None))
    store.insert_visit(conn, _visit("v2", 14, False, 0.0, None, None))
    store.insert_visit(conn, _visit("v3", 14, False, 0.0, None, None))

    summary = build_daily_summary(conn, "booth-01", "2026-09-19")
    assert summary["peak_hour"] == "14"


def test_sample_occupancy_writes_current_and_staff_counts(conn):
    vt = VisitTracker(booth_id="booth-01", stopper_threshold_s=5.0)
    vt.update("cam1:1", "cam1", "stand", 50, 50, 1000.0, is_staff=False)
    vt.update("cam1:2", "cam1", "stand", 50, 50, 1000.0, is_staff=False)
    vt.update("cam1:3", "cam1", "stand", 50, 50, 1000.0, is_staff=True)

    sample_occupancy(conn, "booth-01", vt)

    row = conn.execute("SELECT * FROM occupancy_samples WHERE booth_id='booth-01'").fetchone()
    assert row["current_count"] == 2
    assert row["staff_count"] == 1
