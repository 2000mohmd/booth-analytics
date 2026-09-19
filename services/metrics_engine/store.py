"""SQLite (WAL mode) event store. Schema mirrors the build plan's Section 5 exactly."""
import json
import sqlite3
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


@contextmanager
def cursor(conn: sqlite3.Connection):
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
