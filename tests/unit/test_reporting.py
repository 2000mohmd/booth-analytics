import pytest
from openpyxl import load_workbook

from services.metrics_engine import store
from services.reporting.data import daily_report_data
from services.reporting.excel import export_workbook


@pytest.fixture
def conn(tmp_path):
    conn = store.connect(tmp_path / "events.db")
    store.insert_visit(conn, {
        "visit_id": "v1", "booth_id": "booth-01", "entered_at": "2026-09-19T10:00:00+00:00",
        "exited_at": "2026-09-19T10:00:08+00:00", "zone_path": "aisle→stand", "dwell_seconds": 8.0,
        "is_stopper": True, "is_staff": False, "gender_est": "female", "gender_conf": 0.9,
        "age_bracket": "18-35", "age_conf": 0.9, "position_trace": "10,10;20,20",
    })
    return conn


def test_daily_report_data_shapes(conn):
    data = daily_report_data(conn, "booth-01", "2026-09-19")
    assert data["summary"]["passersby"] == 1
    assert data["dwell_distribution"] == [8.0]
    assert data["hourly_traffic"][0]["hour"] == "10"


def test_excel_export_roundtrip(conn, tmp_path):
    out = export_workbook(conn, "booth-01", str(tmp_path / "export.xlsx"))
    wb = load_workbook(out)
    visits_ws = wb["visits"]
    assert visits_ws.max_row == 2  # header + 1 visit
    assert visits_ws["A2"].value == "v1"
