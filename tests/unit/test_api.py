import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "events.db"))
    monkeypatch.setenv("BOOTH_ID", "booth-01")
    import importlib

    import services.api.main as api_main
    importlib.reload(api_main)  # fresh module-level `conn` bound to the temp DB

    from fastapi.testclient import TestClient

    return TestClient(api_main.app), api_main


def test_health(client):
    tc, _ = client
    assert tc.get("/health").json() == {"status": "ok"}


def test_occupancy_current_defaults_to_zero(client):
    tc, _ = client
    resp = tc.get("/occupancy/current").json()
    assert resp["current_count"] == 0


def test_occupancy_current_reflects_latest_sample(client):
    tc, api_main = client
    from services.metrics_engine import store

    store.insert_occupancy_sample(api_main.conn, "2026-09-19T10:00:00+00:00", "booth-01", 4, 1)
    resp = tc.get("/occupancy/current").json()
    assert resp["current_count"] == 4


def test_alerts_active_empty_initially(client):
    tc, _ = client
    assert tc.get("/alerts/active").json() == []


def test_traffic_hourly_and_dwell_distribution(client):
    tc, api_main = client
    from datetime import date

    from services.metrics_engine import store

    today = date.today().isoformat()
    store.insert_visit(api_main.conn, {
        "visit_id": "v1", "booth_id": "booth-01", "entered_at": f"{today}T10:00:00+00:00",
        "exited_at": f"{today}T10:00:08+00:00", "zone_path": "aisle→stand", "dwell_seconds": 8.0,
        "is_stopper": True, "is_staff": False, "gender_est": "female", "gender_conf": 0.9,
        "age_bracket": "18-35", "age_conf": 0.9, "position_trace": "",
    })
    assert tc.get("/traffic/hourly").json() == [{"hour": "10", "passersby": 1, "stoppers": 1}]
    assert tc.get("/dwell/distribution").json() == [8.0]


def test_totals_today_zero_when_no_visits(client):
    tc, _ = client
    assert tc.get("/totals/today").json() == {
        "passersby": 0, "stoppers": 0, "capture_rate": 0.0, "avg_dwell": 0.0,
    }


def test_totals_today_computes_capture_rate_and_avg_dwell(client):
    tc, api_main = client
    from datetime import date

    from services.metrics_engine import store

    today = date.today().isoformat()
    store.insert_visit(api_main.conn, {
        "visit_id": "v1", "booth_id": "booth-01", "entered_at": f"{today}T10:00:00+00:00",
        "exited_at": f"{today}T10:00:08+00:00", "zone_path": "aisle→stand", "dwell_seconds": 8.0,
        "is_stopper": True, "is_staff": False, "gender_est": "female", "gender_conf": 0.9,
        "age_bracket": "18-35", "age_conf": 0.9, "position_trace": "",
    })
    store.insert_visit(api_main.conn, {
        "visit_id": "v2", "booth_id": "booth-01", "entered_at": f"{today}T11:00:00+00:00",
        "exited_at": f"{today}T11:00:01+00:00", "zone_path": "aisle", "dwell_seconds": 0.0,
        "is_stopper": False, "is_staff": False, "gender_est": None, "gender_conf": None,
        "age_bracket": None, "age_conf": None, "position_trace": "",
    })
    store.insert_visit(api_main.conn, {
        "visit_id": "staff1", "booth_id": "booth-01", "entered_at": f"{today}T09:00:00+00:00",
        "exited_at": f"{today}T09:05:00+00:00", "zone_path": "table", "dwell_seconds": 300.0,
        "is_stopper": True, "is_staff": True, "gender_est": None, "gender_conf": None,
        "age_bracket": None, "age_conf": None, "position_trace": "",
    })

    resp = tc.get("/totals/today").json()
    assert resp["passersby"] == 2       # staff excluded
    assert resp["stoppers"] == 1
    assert resp["capture_rate"] == 0.5
    assert resp["avg_dwell"] == 4.0     # mean of 8.0 and 0.0


def test_demographics_today_empty_when_no_stoppers(client):
    tc, _ = client
    assert tc.get("/demographics/today").json() == {"gender_split": {}, "age_split": {}, "sample_size": 0}


def test_demographics_today_splits_only_stoppers(client):
    tc, api_main = client
    from datetime import date

    from services.metrics_engine import store

    today = date.today().isoformat()
    store.insert_visit(api_main.conn, {
        "visit_id": "v1", "booth_id": "booth-01", "entered_at": f"{today}T10:00:00+00:00",
        "exited_at": f"{today}T10:00:08+00:00", "zone_path": "aisle→stand", "dwell_seconds": 8.0,
        "is_stopper": True, "is_staff": False, "gender_est": "female", "gender_conf": 0.9,
        "age_bracket": "18-35", "age_conf": 0.9, "position_trace": "",
    })
    store.insert_visit(api_main.conn, {
        # a passerby who never stopped - must not count toward the demographics sample
        "visit_id": "v2", "booth_id": "booth-01", "entered_at": f"{today}T11:00:00+00:00",
        "exited_at": f"{today}T11:00:01+00:00", "zone_path": "aisle", "dwell_seconds": 0.0,
        "is_stopper": False, "is_staff": False, "gender_est": None, "gender_conf": None,
        "age_bracket": None, "age_conf": None, "position_trace": "",
    })

    resp = tc.get("/demographics/today").json()
    assert resp["sample_size"] == 1
    assert resp["gender_split"] == {"female": 1.0}
    assert resp["age_split"] == {"18-35": 1.0}


def test_alerts_active_returns_open_alerts(client):
    tc, api_main = client
    from services.metrics_engine import store

    store.open_alert(api_main.conn, "a1", "booth-01", "2026-09-19T10:00:00+00:00", "capacity", "over limit")
    resp = tc.get("/alerts/active").json()
    assert len(resp) == 1
    assert resp[0]["type"] == "capacity"
    assert resp[0]["resolved_at"] is None


def test_unknown_route_returns_404(client):
    tc, _ = client
    assert tc.get("/does/not/exist").status_code == 404


def test_ws_live_pushes_a_snapshot(client):
    tc, _ = client
    with tc.websocket_connect("/ws/live") as ws:
        msg = ws.receive_json()
    assert "occupancy" in msg
    assert "totals" in msg
    assert "active_alerts" in msg
