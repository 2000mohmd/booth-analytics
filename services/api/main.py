"""FastAPI REST + WebSocket API over the local event store. No auth/HTTPS termination here -
this only ever serves the venue's local network, per the architecture doc's jurisdiction boundary."""
import asyncio
import json
import os
from datetime import date, datetime, timezone

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect

from services.common.config import DEFAULT_BOOTH_CONFIG, DEFAULT_BOOTH_ID, DEFAULT_DB_PATH, load_yaml
from services.metrics_engine import store

app = FastAPI(title="booth-analytics-api")

DB_PATH = os.environ.get("DB_PATH", DEFAULT_DB_PATH)
BOOTH_ID = os.environ.get("BOOTH_ID", DEFAULT_BOOTH_ID)
BOOTH_CONFIG = os.environ.get("BOOTH_CONFIG", DEFAULT_BOOTH_CONFIG)
WS_PUSH_INTERVAL_S = 2.0
LIVE_TRACKS_PUSH_INTERVAL_S = 0.3

conn = store.connect(DB_PATH)

_booth = load_yaml(BOOTH_CONFIG)
CAMERA_ZONES = {cam["id"]: cam.get("zones") or {} for cam in _booth["cameras"]}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/occupancy/current")
def occupancy_current():
    return store.get_occupancy_current(conn, BOOTH_ID)


@app.get("/totals/today")
def totals_today():
    return store.get_totals_today(conn, BOOTH_ID, date.today().isoformat())


@app.get("/demographics/today")
def demographics_today():
    return store.get_demographics_today(conn, BOOTH_ID, date.today().isoformat())


@app.get("/traffic/hourly")
def traffic_hourly():
    return store.get_traffic_hourly(conn, BOOTH_ID, date.today().isoformat())


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


@app.get("/tracks/live")
def tracks_live():
    """Anonymized bbox/zone positions only, no imagery - see live_tracks table docstring in
    services/metrics_engine/store.py. Powers the debug live-track dashboard page, not raw video."""
    by_camera: dict[str, dict] = {
        cam_id: {"zones": zones, "frame_w": 0, "frame_h": 0, "tracks": []}
        for cam_id, zones in CAMERA_ZONES.items()
    }
    for row in store.get_live_cameras(conn):
        cam = by_camera.setdefault(row["camera_id"], {"zones": {}, "frame_w": 0, "frame_h": 0, "tracks": []})
        cam["frame_w"], cam["frame_h"] = row["frame_w"], row["frame_h"]
    for row in store.get_live_tracks(conn):
        cam = by_camera.setdefault(row["camera_id"], {"zones": {}, "frame_w": 0, "frame_h": 0, "tracks": []})
        cam["tracks"].append({
            "track_id": row["track_id"], "x1": row["x1"], "y1": row["y1"],
            "x2": row["x2"], "y2": row["y2"], "zone": row["zone"],
        })
    return by_camera


@app.get("/debug/video/{camera_id}")
def debug_video_frame(camera_id: str):
    """Latest raw camera frame with box overlays, as a single JPEG - only populated for overhead
    cameras when ingestion runs with debug_video_stream enabled (on by default - see
    services/ingestion/pipeline.py's live_debug_frames writes and
    services/metrics_engine/store.py's live_debug_frames table docstring). A deliberate, scoped
    exception to this project's normal no-raw-video boundary. The kiosk display
    (services/kiosk_display) is the primary consumer in production; this endpoint also backs
    the dashboard's /live debug page. Never returns eye-level camera frames - that camera never
    writes to live_debug_frames at all.

    Polled by the dashboard rather than served as MJPEG (multipart/x-mixed-replace): Chromium
    doesn't reliably render MJPEG in an <img>, so a polled single frame is the portable option."""
    row = store.get_live_debug_frame(conn, camera_id)
    if row is None:
        return Response(status_code=404)
    return Response(content=bytes(row["jpg"]), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@app.websocket("/ws/tracks")
async def ws_tracks(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_text(json.dumps(tracks_live()))
            await asyncio.sleep(LIVE_TRACKS_PUSH_INTERVAL_S)
    except WebSocketDisconnect:
        pass


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
