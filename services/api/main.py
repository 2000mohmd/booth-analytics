"""FastAPI REST + WebSocket API over the local event store. No auth/HTTPS termination here -
this only ever serves the venue's local network, per the architecture doc's jurisdiction boundary."""
import asyncio
import json
import os
from datetime import date, datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from services.metrics_engine import store

app = FastAPI(title="booth-analytics-api")

DB_PATH = os.environ.get("DB_PATH", "data/events.db")
BOOTH_ID = os.environ.get("BOOTH_ID", "booth-01")
WS_PUSH_INTERVAL_S = 2.0

conn = store.connect(DB_PATH)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/occupancy/current")
def occupancy_current():
    row = conn.execute(
        "SELECT * FROM occupancy_samples WHERE booth_id=? ORDER BY ts DESC LIMIT 1", (BOOTH_ID,)
    ).fetchone()
    return dict(row) if row else {"current_count": 0, "staff_count": 0, "ts": None}


@app.get("/totals/today")
def totals_today():
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS passersby, SUM(is_stopper) AS stoppers, AVG(dwell_seconds) AS avg_dwell "
        "FROM visits WHERE booth_id=? AND substr(entered_at,1,10)=? AND is_staff=0",
        (BOOTH_ID, today),
    ).fetchone()
    passersby = row["passersby"] or 0
    stoppers = row["stoppers"] or 0
    return {
        "passersby": passersby,
        "stoppers": stoppers,
        "capture_rate": round(stoppers / passersby, 3) if passersby else 0.0,
        "avg_dwell": round(row["avg_dwell"], 2) if row["avg_dwell"] else 0.0,
    }


@app.get("/demographics/today")
def demographics_today():
    today = date.today().isoformat()
    rows = conn.execute(
        "SELECT gender_est, age_bracket FROM visits "
        "WHERE booth_id=? AND substr(entered_at,1,10)=? AND is_staff=0 AND is_stopper=1",
        (BOOTH_ID, today),
    ).fetchall()

    def _split(values):
        values = [v for v in values if v and v != "unknown"]
        if not values:
            return {}
        counts: dict[str, int] = {}
        for v in values:
            counts[v] = counts.get(v, 0) + 1
        return {k: round(v / len(values), 3) for k, v in counts.items()}

    return {
        "gender_split": _split([r["gender_est"] for r in rows]),
        "age_split": _split([r["age_bracket"] for r in rows]),
        "sample_size": len(rows),
    }


@app.get("/traffic/hourly")
def traffic_hourly():
    today = date.today().isoformat()
    rows = conn.execute(
        "SELECT substr(entered_at,12,2) AS hour, COUNT(*) AS passersby, SUM(is_stopper) AS stoppers "
        "FROM visits WHERE booth_id=? AND substr(entered_at,1,10)=? AND is_staff=0 "
        "GROUP BY hour ORDER BY hour",
        (BOOTH_ID, today),
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/dwell/distribution")
def dwell_distribution():
    today = date.today().isoformat()
    rows = conn.execute(
        "SELECT dwell_seconds FROM visits WHERE booth_id=? AND substr(entered_at,1,10)=? "
        "AND is_staff=0 AND is_stopper=1",
        (BOOTH_ID, today),
    ).fetchall()
    return [r["dwell_seconds"] for r in rows]


@app.get("/alerts/active")
def alerts_active():
    return [dict(r) for r in store.active_alerts(conn, BOOTH_ID)]


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_text(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "occupancy": occupancy_current(),
                "totals": totals_today(),
                "active_alerts": alerts_active(),
            }))
            await asyncio.sleep(WS_PUSH_INTERVAL_S)
    except WebSocketDisconnect:
        pass
