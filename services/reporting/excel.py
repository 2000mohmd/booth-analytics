"""Raw CSV/Excel export of visits + daily_summary, anonymized (matches what's already in the DB)."""
from openpyxl import Workbook


def export_workbook(conn, booth_id: str, out_path: str) -> str:
    wb = Workbook()

    visits_ws = wb.active
    visits_ws.title = "visits"
    visit_cols = ["visit_id", "entered_at", "exited_at", "zone_path", "dwell_seconds",
                  "is_stopper", "gender_est", "gender_conf", "age_bracket", "age_conf"]
    visits_ws.append(visit_cols)
    for row in conn.execute(
        "SELECT * FROM visits WHERE booth_id=? AND is_staff=0 ORDER BY entered_at", (booth_id,)
    ):
        visits_ws.append([row[c] for c in visit_cols])

    summary_ws = wb.create_sheet("daily_summary")
    summary_cols = ["day", "passersby", "stoppers", "capture_rate", "avg_dwell", "median_dwell",
                     "gender_split", "age_split", "peak_hour"]
    summary_ws.append(summary_cols)
    for row in conn.execute(
        "SELECT * FROM daily_summary WHERE booth_id=? ORDER BY day", (booth_id,)
    ):
        values = [row[c] for c in summary_cols]
        summary_ws.append(values)

    wb.save(out_path)
    return out_path
