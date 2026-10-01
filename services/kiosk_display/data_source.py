"""Read-only data access for the kiosk display - polls the same SQLite DB ingestion writes to,
never writes anything itself (PRAGMA query_only=ON enforces this at the connection level, not
just by convention).

Camera video access is deliberately restricted to overhead cameras only. The eye-level camera's
entire purpose is capturing frontal faces for age/gender estimation - showing its feed on a
public marketing screen would defeat the anonymization premise regardless of camera angle.
fetch_frame() refuses any camera_id not declared with role: overhead in booth.yaml, so this
can't be bypassed by a caller mistake elsewhere in the app.
"""
import logging
import sqlite3

from services.common.config import load_yaml
from services.metrics_engine import store

log = logging.getLogger(__name__)


def _load_overhead_camera_ids(booth_config_path: str) -> set[str]:
    booth = load_yaml(booth_config_path)
    return {cam["id"] for cam in booth["cameras"] if cam["role"] == "overhead"}


class KioskDataSource:
    def __init__(self, db_path: str, booth_config_path: str, booth_id: str = "booth-01"):
        self.booth_id = booth_id
        self.overhead_camera_ids = _load_overhead_camera_ids(booth_config_path)
        if not self.overhead_camera_ids:
            raise ValueError(f"{booth_config_path} has no camera with role: overhead - "
                              f"nothing for the kiosk display to show")
        log.info("kiosk display restricted to overhead cameras: %s", sorted(self.overhead_camera_ids))

        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA query_only=ON")

    def fetch_live_state(self) -> dict:
        """Anonymized per-camera track/zone data plus today's aggregate totals - safe to poll
        frequently, never touches raw imagery. Wrapped so a transient DB hiccup (e.g. ingestion
        mid-restart) degrades to an empty-but-valid result instead of raising into the render
        loop - see main.py's timer callback for how callers should treat an empty result as
        "no fresh data right now", not an error."""
        try:
            cameras: dict[str, dict] = {
                cid: {"frame_w": 0, "frame_h": 0, "tracks": []} for cid in self.overhead_camera_ids
            }
            for row in store.get_live_cameras(self._conn):
                if row["camera_id"] not in cameras:
                    continue  # eye-level camera's live_cameras row exists too - not our concern here
                cameras[row["camera_id"]]["frame_w"] = row["frame_w"]
                cameras[row["camera_id"]]["frame_h"] = row["frame_h"]
            for row in store.get_live_tracks(self._conn):
                if row["camera_id"] not in cameras:
                    continue
                cameras[row["camera_id"]]["tracks"].append({
                    "track_id": row["track_id"], "x1": row["x1"], "y1": row["y1"],
                    "x2": row["x2"], "y2": row["y2"], "zone": row["zone"],
                })
            return {"cameras": cameras, "totals": self._fetch_totals(), "occupancy": self._fetch_occupancy()}
        except sqlite3.OperationalError as e:
            log.warning("live state poll failed (DB busy/locked?), returning empty: %s", e)
            return {"cameras": {cid: {"frame_w": 0, "frame_h": 0, "tracks": []}
                                for cid in self.overhead_camera_ids},
                    "totals": None, "occupancy": None}

    def fetch_frame(self, camera_id: str) -> bytes | None:
        """Latest JPEG (boxes already burned in server-side) for one overhead camera. Refuses
        any camera_id not in self.overhead_camera_ids - see module docstring."""
        if camera_id not in self.overhead_camera_ids:
            raise ValueError(f"refusing to fetch video for '{camera_id}' - only overhead "
                              f"cameras {sorted(self.overhead_camera_ids)} may be displayed")
        try:
            row = store.get_live_debug_frame(self._conn, camera_id)
        except sqlite3.OperationalError as e:
            log.warning("frame poll failed for %s (DB busy/locked?): %s", camera_id, e)
            return None
        return bytes(row["jpg"]) if row is not None else None

    def _fetch_totals(self) -> dict | None:
        import datetime

        return store.get_totals_today(self._conn, self.booth_id, datetime.date.today().isoformat())

    def _fetch_occupancy(self) -> dict | None:
        return store.get_occupancy_current(self._conn, self.booth_id)
