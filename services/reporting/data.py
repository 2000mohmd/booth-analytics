"""Pure data-gathering for reports - no rendering deps here, so this is testable without
WeasyPrint/openpyxl even being installed. pdf.py and excel.py just format what this returns.
"""
from services.metrics_engine.occupancy import build_daily_summary


def daily_report_data(conn, booth_id: str, day: str) -> dict:
    summary = build_daily_summary(conn, booth_id, day)
    hourly = conn.execute(
        "SELECT substr(entered_at,12,2) AS hour, COUNT(*) AS passersby, SUM(is_stopper) AS stoppers "
        "FROM visits WHERE booth_id=? AND substr(entered_at,1,10)=? AND is_staff=0 "
        "GROUP BY hour ORDER BY hour",
        (booth_id, day),
    ).fetchall()
    dwell_rows = conn.execute(
        "SELECT dwell_seconds FROM visits WHERE booth_id=? AND substr(entered_at,1,10)=? "
        "AND is_staff=0 AND is_stopper=1",
        (booth_id, day),
    ).fetchall()
    return {
        "summary": summary,
        "hourly_traffic": [dict(r) for r in hourly],
        "dwell_distribution": [r["dwell_seconds"] for r in dwell_rows],
    }


def final_report_data(conn, booth_id: str, days: list[str]) -> dict:
    return {"days": [daily_report_data(conn, booth_id, d) for d in days]}
