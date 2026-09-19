from services.alerting.main import tick
from services.metrics_engine import store

THRESHOLDS = {"capacity_max_occupancy": 5, "traffic_spike_per_minute": 3}


def test_capacity_alert_opens_and_resolves(tmp_path):
    conn = store.connect(tmp_path / "events.db")
    store.insert_occupancy_sample(conn, "2026-09-19T10:00:00+00:00", "booth-01", 8, 1)

    tick(conn, "booth-01", THRESHOLDS, webhook_url=None)
    active = store.active_alerts(conn, "booth-01")
    assert any(a["type"] == "capacity" for a in active)

    store.insert_occupancy_sample(conn, "2026-09-19T10:01:00+00:00", "booth-01", 2, 1)
    tick(conn, "booth-01", THRESHOLDS, webhook_url=None)
    active = store.active_alerts(conn, "booth-01")
    assert not any(a["type"] == "capacity" for a in active)


def test_no_alert_without_any_occupancy_sample(tmp_path):
    conn = store.connect(tmp_path / "events.db")
    tick(conn, "booth-01", THRESHOLDS, webhook_url=None)
    assert store.active_alerts(conn, "booth-01") == []
