"""Periodic occupancy sampling and end-of-day aggregation into daily_summary."""
import statistics
from datetime import datetime, timezone

from services.metrics_engine import store


def sample_occupancy(conn, booth_id: str, visit_tracker) -> None:
    now = datetime.now(timezone.utc).isoformat()
    store.insert_occupancy_sample(
        conn, now, booth_id,
        current_count=visit_tracker.active_count(exclude_staff=True),
        staff_count=visit_tracker.staff_count(),
    )


def build_daily_summary(conn, booth_id: str, day: str) -> dict:
    """day: 'YYYY-MM-DD'. Reads all visits whose entered_at falls on that day."""
    rows = conn.execute(
        "SELECT * FROM visits WHERE booth_id=? AND substr(entered_at,1,10)=? AND is_staff=0",
        (booth_id, day),
    ).fetchall()

    passersby = len(rows)
    stoppers = [r for r in rows if r["is_stopper"]]
    dwells = [r["dwell_seconds"] for r in stoppers if r["dwell_seconds"] is not None]

    genders = [r["gender_est"] for r in rows if r["gender_est"] and r["gender_est"] != "unknown"]
    ages = [r["age_bracket"] for r in rows if r["age_bracket"] and r["age_bracket"] != "unknown"]

    def _split(values):
        if not values:
            return {}
        total = len(values)
        counts: dict[str, int] = {}
        for v in values:
            counts[v] = counts.get(v, 0) + 1
        return {k: round(v / total, 3) for k, v in counts.items()}

    hours = [r["entered_at"][11:13] for r in rows if r["entered_at"]]
    peak_hour = max(set(hours), key=hours.count) if hours else None

    summary = {
        "booth_id": booth_id,
        "day": day,
        "passersby": passersby,
        "stoppers": len(stoppers),
        "capture_rate": round(len(stoppers) / passersby, 3) if passersby else 0.0,
        "avg_dwell": round(statistics.mean(dwells), 2) if dwells else 0.0,
        "median_dwell": round(statistics.median(dwells), 2) if dwells else 0.0,
        "gender_split": _split(genders),
        "age_split": _split(ages),
        "peak_hour": peak_hour,
    }
    store.upsert_daily_summary(conn, summary)
    return summary
