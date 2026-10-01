"""SQLite (WAL mode) event store. Schema mirrors the build plan's Section 5 exactly."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
  visit_id       TEXT PRIMARY KEY,
  booth_id       TEXT NOT NULL,
  entered_at     TEXT NOT NULL,
  exited_at      TEXT,
  zone_path      TEXT,
  dwell_seconds  REAL,
  is_stopper     BOOLEAN,
  is_staff       BOOLEAN DEFAULT FALSE,
  gender_est     TEXT,
  gender_conf    REAL,
  age_bracket    TEXT,
  age_conf       REAL,
  position_trace TEXT
);

CREATE TABLE IF NOT EXISTS occupancy_samples (
  ts             TEXT NOT NULL,
  booth_id       TEXT NOT NULL,
  current_count  INTEGER,
  staff_count    INTEGER
);

CREATE TABLE IF NOT EXISTS alerts (
  alert_id       TEXT PRIMARY KEY,
  booth_id       TEXT NOT NULL,
  ts             TEXT NOT NULL,
  type           TEXT,
  detail         TEXT,
  resolved_at    TEXT
);

CREATE TABLE IF NOT EXISTS live_cameras (
  camera_id      TEXT PRIMARY KEY,
  frame_w        INTEGER,
  frame_h        INTEGER,
  ts             REAL NOT NULL
);

-- DELIBERATE, SCOPED EXCEPTION to this project's default "raw video never leaves ingestion /
-- never persists" boundary (README.md) - populated for OVERHEAD cameras only (never the
-- eye-level camera - see services/ingestion/pipeline.py's run_eyelevel_camera, which has no
-- code path that writes here at all) whenever ingestion runs with debug_video_stream enabled
-- (on by default - see services/ingestion/main.py). This powers two things: the marketing
-- kiosk display (services/kiosk_display), which needs real overhead-camera video, and the
-- dashboard's /live debug page. Overhead cameras are high-angle by design (mostly
-- heads/shoulders, not frontal faces) which is the load-bearing assumption behind showing this
-- publicly at all - see the deployment plan's reasoning if that assumption is ever revisited.
-- One row per camera, always overwritten, never queried historically - nothing here is meant
-- to accumulate or be retained beyond "whatever's currently on screen."
CREATE TABLE IF NOT EXISTS live_debug_frames (
  camera_id      TEXT PRIMARY KEY,
  jpg            BLOB NOT NULL,
  ts             REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS live_tracks (
  camera_id      TEXT NOT NULL,
  track_id       TEXT NOT NULL,
  x1 REAL, y1 REAL, x2 REAL, y2 REAL,
  zone           TEXT,
  frame_w        INTEGER,
  frame_h        INTEGER,
  ts             REAL NOT NULL,
  PRIMARY KEY (camera_id, track_id)
);

CREATE TABLE IF NOT EXISTS daily_summary (
  booth_id       TEXT NOT NULL,
  day            TEXT NOT NULL,
  passersby      INTEGER,
  stoppers       INTEGER,
  capture_rate   REAL,
  avg_dwell      REAL,
  median_dwell   REAL,
  gender_split   TEXT,
  age_split      TEXT,
  peak_hour      TEXT,
  PRIMARY KEY (booth_id, day)
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# One connection is shared by every camera thread in the ingestion process (check_same_thread=
# False only disables Python's guard - it doesn't make concurrent use safe). Unserialized
# writes from several threads raise sqlite3.InterfaceError ("bad parameter or other API misuse").
_write_lock = threading.RLock()


@contextmanager
def cursor(conn: sqlite3.Connection):
    with _write_lock:
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        finally:
            cur.close()


def insert_visit(conn, visit: dict):
    """Creates or fully overwrites a visit row (used at track creation, or by tests/imports
    that supply a complete row). Never call this after demographics have been attached to an
    in-progress visit - it would blow away gender_est/age_bracket. Use finalize_visit() for that."""
    with cursor(conn) as cur:
        cur.execute(
            """INSERT OR REPLACE INTO visits
               (visit_id, booth_id, entered_at, exited_at, zone_path, dwell_seconds,
                is_stopper, is_staff, gender_est, gender_conf, age_bracket, age_conf, position_trace)
               VALUES (:visit_id, :booth_id, :entered_at, :exited_at, :zone_path, :dwell_seconds,
                       :is_stopper, :is_staff, :gender_est, :gender_conf, :age_bracket, :age_conf, :position_trace)""",
            visit,
        )


def finalize_visit(conn, visit: dict):
    """Updates only the fields dwell.VisitTracker.finalize() computes - leaves gender_est/
    age_bracket alone, since the eye-level camera may have already attached those to this
    visit_id while the track was still active (before it had a finalized row to update)."""
    with cursor(conn) as cur:
        cur.execute(
            """UPDATE visits SET exited_at=:exited_at, zone_path=:zone_path,
               dwell_seconds=:dwell_seconds, is_stopper=:is_stopper, is_staff=:is_staff,
               position_trace=:position_trace
               WHERE visit_id=:visit_id""",
            visit,
        )


def update_visit_demographics(conn, visit_id: str, gender_est: str, gender_conf: float,
                               age_bracket: str, age_conf: float):
    with cursor(conn) as cur:
        cur.execute(
            "UPDATE visits SET gender_est=?, gender_conf=?, age_bracket=?, age_conf=? WHERE visit_id=?",
            (gender_est, gender_conf, age_bracket, age_conf, visit_id),
        )


def insert_occupancy_sample(conn, ts: str, booth_id: str, current_count: int, staff_count: int):
    with cursor(conn) as cur:
        cur.execute(
            "INSERT INTO occupancy_samples (ts, booth_id, current_count, staff_count) VALUES (?, ?, ?, ?)",
            (ts, booth_id, current_count, staff_count),
        )


def open_alert(conn, alert_id: str, booth_id: str, ts: str, alert_type: str, detail: str):
    with cursor(conn) as cur:
        cur.execute(
            "INSERT INTO alerts (alert_id, booth_id, ts, type, detail, resolved_at) VALUES (?, ?, ?, ?, ?, NULL)",
            (alert_id, booth_id, ts, alert_type, detail),
        )


def resolve_alert(conn, alert_id: str, resolved_at: str):
    with cursor(conn) as cur:
        cur.execute("UPDATE alerts SET resolved_at=? WHERE alert_id=?", (resolved_at, alert_id))


def active_alerts(conn, booth_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM alerts WHERE booth_id=? AND resolved_at IS NULL ORDER BY ts DESC", (booth_id,)
    ).fetchall()


# --- Aggregate queries shared by services/api, services/cloud_sync, services/kiosk_display,
# and services/reporting - centralized here (rather than each service reimplementing the same
# SQL) so there's exactly one place that knows what "today's totals" or "hourly traffic" means.

def get_occupancy_current(conn, booth_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM occupancy_samples WHERE booth_id=? ORDER BY ts DESC LIMIT 1", (booth_id,)
    ).fetchone()
    return dict(row) if row else {"current_count": 0, "staff_count": 0, "ts": None}


def get_totals_today(conn, booth_id: str, today: str) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS passersby, SUM(is_stopper) AS stoppers, AVG(dwell_seconds) AS avg_dwell "
        "FROM visits WHERE booth_id=? AND substr(entered_at,1,10)=? AND is_staff=0",
        (booth_id, today),
    ).fetchone()
    passersby = row["passersby"] or 0
    stoppers = row["stoppers"] or 0
    return {
        "passersby": passersby,
        "stoppers": stoppers,
        "capture_rate": round(stoppers / passersby, 3) if passersby else 0.0,
        "avg_dwell": round(row["avg_dwell"], 2) if row["avg_dwell"] else 0.0,
    }


def get_demographics_today(conn, booth_id: str, today: str) -> dict:
    rows = conn.execute(
        "SELECT gender_est, age_bracket FROM visits "
        "WHERE booth_id=? AND substr(entered_at,1,10)=? AND is_staff=0 AND is_stopper=1",
        (booth_id, today),
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


def get_traffic_hourly(conn, booth_id: str, day: str) -> list[dict]:
    rows = conn.execute(
        "SELECT substr(entered_at,12,2) AS hour, COUNT(*) AS passersby, SUM(is_stopper) AS stoppers "
        "FROM visits WHERE booth_id=? AND substr(entered_at,1,10)=? AND is_staff=0 "
        "GROUP BY hour ORDER BY hour",
        (booth_id, day),
    ).fetchall()
    return [dict(r) for r in rows]


def replace_live_tracks(conn, camera_id: str, ts: float, frame_w: int, frame_h: int, tracks: list[dict]):
    """Overwrites this camera's live_tracks rows with its current tick's tracks (bbox + zone
    only - no imagery, no biometric identity) for the debug live-track view. Ephemeral by
    design: full delete+reinsert each call, nothing here is meant to accumulate history.

    Frame dimensions are recorded separately in live_cameras (not just alongside each track
    row) so a camera with zero people in frame still reports its size to the live view."""
    with cursor(conn) as cur:
        cur.execute(
            "INSERT OR REPLACE INTO live_cameras (camera_id, frame_w, frame_h, ts) VALUES (?, ?, ?, ?)",
            (camera_id, frame_w, frame_h, ts),
        )
        cur.execute("DELETE FROM live_tracks WHERE camera_id=?", (camera_id,))
        cur.executemany(
            """INSERT INTO live_tracks (camera_id, track_id, x1, y1, x2, y2, zone, frame_w, frame_h, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (camera_id, t["track_id"], t["x1"], t["y1"], t["x2"], t["y2"], t.get("zone"),
                 frame_w, frame_h, ts)
                for t in tracks
            ],
        )


def set_live_debug_frame(conn, camera_id: str, ts: float, jpg_bytes: bytes):
    with cursor(conn) as cur:
        cur.execute(
            "INSERT OR REPLACE INTO live_debug_frames (camera_id, jpg, ts) VALUES (?, ?, ?)",
            (camera_id, jpg_bytes, ts),
        )


def get_live_debug_frame(conn, camera_id: str, max_age_s: float = 6.0, now: float | None = None) -> sqlite3.Row | None:
    import time as _time

    cutoff = (now if now is not None else _time.time()) - max_age_s
    return conn.execute(
        "SELECT * FROM live_debug_frames WHERE camera_id=? AND ts >= ?", (camera_id, cutoff),
    ).fetchone()


def get_live_cameras(conn, max_age_s: float = 6.0, now: float | None = None) -> list[sqlite3.Row]:
    import time as _time

    cutoff = (now if now is not None else _time.time()) - max_age_s
    return conn.execute("SELECT * FROM live_cameras WHERE ts >= ?", (cutoff,)).fetchall()


def get_live_tracks(conn, max_age_s: float = 6.0, now: float | None = None) -> list[sqlite3.Row]:
    """Rows fresher than max_age_s - an ingestion process that died mid-stream shouldn't leave
    ghost boxes on the live view forever."""
    import time as _time

    cutoff = (now if now is not None else _time.time()) - max_age_s
    return conn.execute("SELECT * FROM live_tracks WHERE ts >= ?", (cutoff,)).fetchall()


def upsert_daily_summary(conn, summary: dict):
    row = dict(summary)
    row["gender_split"] = json.dumps(row.get("gender_split") or {})
    row["age_split"] = json.dumps(row.get("age_split") or {})
    with cursor(conn) as cur:
        cur.execute(
            """INSERT OR REPLACE INTO daily_summary
               (booth_id, day, passersby, stoppers, capture_rate, avg_dwell, median_dwell,
                gender_split, age_split, peak_hour)
               VALUES (:booth_id, :day, :passersby, :stoppers, :capture_rate, :avg_dwell, :median_dwell,
                       :gender_split, :age_split, :peak_hour)""",
            row,
        )
