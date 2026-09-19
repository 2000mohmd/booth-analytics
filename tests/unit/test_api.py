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
