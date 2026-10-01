import pytest

from services.cloud_sync.payload import build_sync_payload
from services.metrics_engine import store


@pytest.fixture
def conn(tmp_path):
    return store.connect(tmp_path / "events.db")


def _visit(visit_id, **overrides):
    row = {
        "visit_id": visit_id, "booth_id": "booth-01", "entered_at": "2026-09-19T10:00:00+00:00",
        "exited_at": "2026-09-19T10:00:05+00:00", "zone_path": "aisle→stand", "dwell_seconds": 5.0,
        "is_stopper": True, "is_staff": False, "gender_est": "female", "gender_conf": 0.9,
        "age_bracket": "18-35", "age_conf": 0.8, "position_trace": "10,10;20,20",
    }
    row.update(overrides)
    return row


def test_empty_db_returns_zeroed_payload(conn):
    payload = build_sync_payload(conn, "booth-01")
    # occupancy comes from the shared services.metrics_engine.store.get_occupancy_current(),
    # which also includes "ts" (None when there's no sample yet) - a superset of the old
    # cloud_sync-only shape, not a behavior change for any real consumer.
    assert payload["occupancy"] == {"current_count": 0, "staff_count": 0, "ts": None}
    assert payload["totals_today"]["passersby"] == 0
    assert payload["booth_id"] == "booth-01"


def test_payload_never_includes_raw_track_or_video_fields(conn):
    """The whole point of this module - assert the forbidden keys never sneak in, not just
    that we didn't happen to write code that includes them."""
    payload = build_sync_payload(conn, "booth-01")
    forbidden = {"live_tracks", "live_cameras", "live_debug_frames", "tracks", "jpg", "frame",
                 "video", "bbox", "x1", "y1", "x2", "y2"}

    def _walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert k not in forbidden, f"forbidden key '{k}' found in cloud sync payload"
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(payload)


def test_payload_never_includes_individual_visit_ids(conn):
    """Aggregate-only means aggregate-only - no per-visitor rows, even anonymized ones."""
    store.insert_visit(conn, _visit("v1"))
    payload = build_sync_payload(conn, "booth-01")
    serialized = str(payload)
    assert "v1" not in serialized


def test_totals_reflect_todays_visits(conn):
    import datetime

    today = datetime.date.today().isoformat()
    store.insert_visit(conn, _visit("v1", entered_at=f"{today}T10:00:00+00:00", is_stopper=True))
    store.insert_visit(conn, _visit("v2", entered_at=f"{today}T11:00:00+00:00", is_stopper=False))
    payload = build_sync_payload(conn, "booth-01")
    assert payload["totals_today"]["passersby"] == 2
    assert payload["totals_today"]["stoppers"] == 1
    assert payload["totals_today"]["capture_rate"] == 0.5


def test_staff_visits_excluded_from_totals(conn):
    import datetime

    today = datetime.date.today().isoformat()
    store.insert_visit(conn, _visit("v1", entered_at=f"{today}T10:00:00+00:00", is_staff=True))
    payload = build_sync_payload(conn, "booth-01")
    assert payload["totals_today"]["passersby"] == 0
