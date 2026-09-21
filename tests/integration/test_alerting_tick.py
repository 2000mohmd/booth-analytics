import http.server
import threading
from datetime import datetime, timedelta, timezone

from services.alerting.main import send_webhook, tick
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


def test_no_coverage_alert_opens_and_resolves(tmp_path):
    conn = store.connect(tmp_path / "events.db")
    store.insert_occupancy_sample(conn, "2026-09-19T10:00:00+00:00", "booth-01", 3, 0)

    tick(conn, "booth-01", THRESHOLDS, webhook_url=None)
    active = store.active_alerts(conn, "booth-01")
    assert any(a["type"] == "no_coverage" for a in active)

    store.insert_occupancy_sample(conn, "2026-09-19T10:01:00+00:00", "booth-01", 3, 1)
    tick(conn, "booth-01", THRESHOLDS, webhook_url=None)
    active = store.active_alerts(conn, "booth-01")
    assert not any(a["type"] == "no_coverage" for a in active)


def test_traffic_spike_alert_opens_from_recent_stoppers(tmp_path):
    conn = store.connect(tmp_path / "events.db")
    store.insert_occupancy_sample(conn, "2026-09-19T10:00:00+00:00", "booth-01", 2, 1)

    now = datetime.now(timezone.utc)
    for i in range(3):  # meets traffic_spike_per_minute=3 within the 60s spike window
        store.insert_visit(conn, {
            "visit_id": f"v{i}", "booth_id": "booth-01",
            "entered_at": (now - timedelta(seconds=i)).isoformat(),
            "exited_at": None, "zone_path": "stand", "dwell_seconds": 6.0,
            "is_stopper": True, "is_staff": False, "gender_est": None, "gender_conf": None,
            "age_bracket": None, "age_conf": None, "position_trace": "",
        })

    tick(conn, "booth-01", THRESHOLDS, webhook_url=None)
    active = store.active_alerts(conn, "booth-01")
    assert any(a["type"] == "traffic_spike" for a in active)


def test_multiple_alert_types_can_be_active_simultaneously(tmp_path):
    conn = store.connect(tmp_path / "events.db")
    store.insert_occupancy_sample(conn, "2026-09-19T10:00:00+00:00", "booth-01", 8, 0)

    tick(conn, "booth-01", THRESHOLDS, webhook_url=None)
    active_types = {a["type"] for a in store.active_alerts(conn, "booth-01")}
    assert active_types == {"capacity", "no_coverage"}


def test_alert_already_active_is_not_reopened(tmp_path):
    """A condition that's still true on the next tick must keep the same alert row (same
    alert_id), not open a duplicate."""
    conn = store.connect(tmp_path / "events.db")
    store.insert_occupancy_sample(conn, "2026-09-19T10:00:00+00:00", "booth-01", 8, 1)

    tick(conn, "booth-01", THRESHOLDS, webhook_url=None)
    first_id = next(a["alert_id"] for a in store.active_alerts(conn, "booth-01") if a["type"] == "capacity")

    store.insert_occupancy_sample(conn, "2026-09-19T10:00:05+00:00", "booth-01", 9, 1)
    tick(conn, "booth-01", THRESHOLDS, webhook_url=None)
    active = store.active_alerts(conn, "booth-01")
    capacity_alerts = [a for a in active if a["type"] == "capacity"]

    assert len(capacity_alerts) == 1
    assert capacity_alerts[0]["alert_id"] == first_id


def test_send_webhook_delivers_payload_to_a_real_listener():
    received = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received.append(self.rfile.read(length))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):  # silence default stderr logging
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    try:
        send_webhook(f"http://127.0.0.1:{server.server_port}/hook", {"alert_id": "a1", "type": "capacity"})
    finally:
        thread.join(timeout=5)
        server.server_close()

    assert len(received) == 1
    assert b'"alert_id": "a1"' in received[0]


def test_send_webhook_failure_does_not_raise():
    """Webhook delivery is best-effort - a connection failure must be swallowed, never crash
    the alert loop calling it."""
    send_webhook("http://127.0.0.1:1/unreachable", {"alert_id": "a1"})  # port 1: connection refused


def test_send_webhook_noop_without_url():
    send_webhook(None, {"alert_id": "a1"})
