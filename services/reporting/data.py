"""Pure data-gathering for reports - no rendering deps here, so this is testable without
WeasyPrint/openpyxl even being installed. pdf.py and excel.py just format what this returns.
"""
from services.metrics_engine import store
from services.metrics_engine.occupancy import build_daily_summary


def daily_report_data(conn, booth_id: str, day: str) -> dict:
    summary = build_daily_summary(conn, booth_id, day)
    hourly = store.get_traffic_hourly(conn, booth_id, day)
    dwell_rows = conn.execute(
        "SELECT dwell_seconds FROM visits WHERE booth_id=? AND substr(entered_at,1,10)=? "
        "AND is_staff=0 AND is_stopper=1",
        (booth_id, day),
    ).fetchall()
    return {
        "summary": summary,
        "hourly_traffic": hourly,
        "dwell_distribution": [r["dwell_seconds"] for r in dwell_rows],
    }


def final_report_data(conn, booth_id: str, days: list[str]) -> dict:
    return {"days": [daily_report_data(conn, booth_id, d) for d in days]}
