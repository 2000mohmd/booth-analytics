"""Builds the aggregate-only payload sent to the cloud. Pure data-gathering, no network -
testable without a live endpoint, mirroring services/reporting/data.py's separation.

What's included here is the full set of what this project ever sends to the cloud - if you're
checking whether something is exposed remotely, this function is the single place to look.
Uses the same shared aggregate queries services/api/main.py's REST endpoints use
(services/metrics_engine/store.py's get_occupancy_current/get_totals_today/
get_demographics_today/get_traffic_hourly/active_alerts) rather than reimplementing the SQL
here - one query, one definition of "today's totals".

Deliberately excluded, always: live_tracks, live_cameras, live_debug_frames (per-track bbox/
video data), and individual visits rows (raw per-visitor records, even anonymized ones could in
principle be re-identified by cross-referencing entry/exit timestamps) - only pre-aggregated
counts/percentages ever leave the venue network.
"""
import datetime

from services.metrics_engine import store


def build_sync_payload(conn, booth_id: str) -> dict:
    today = datetime.date.today().isoformat()

    hourly_rows = store.get_traffic_hourly(conn, booth_id, today)
    alert_rows = store.active_alerts(conn, booth_id)
    daily_summary_rows = conn.execute(
        "SELECT * FROM daily_summary WHERE booth_id=? ORDER BY day DESC LIMIT 30", (booth_id,),
    ).fetchall()

    return {
        "booth_id": booth_id,
        "synced_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "occupancy": store.get_occupancy_current(conn, booth_id),
        "totals_today": store.get_totals_today(conn, booth_id, today),
        "demographics_today": store.get_demographics_today(conn, booth_id, today),
        "hourly_traffic_today": hourly_rows,
        "active_alerts": [dict(r) for r in alert_rows],
        "daily_summaries": [dict(r) for r in daily_summary_rows],
    }
