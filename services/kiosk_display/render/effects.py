"""Client-side motion trails and appearance pulses, computed from successive polled track
positions - see data_source.py's fetch_live_state(). Purely a visual accent layered on top of
the server-drawn boxes already burned into the video frame (services/ingestion/pipeline.py's
_draw_tracks); this module never touches imagery, only the numeric track rows.
"""
import time
from dataclasses import dataclass, field

TRAIL_WINDOW_S = 1.5
PULSE_DURATION_S = 0.6


@dataclass
class _TrackState:
    points: list[tuple[float, float, float]] = field(default_factory=list)  # (x, y, ts)
    first_seen: float = 0.0


class TrailTracker:
    """One instance per camera_id (or share across cameras by namespacing track_id yourself -
    kiosk_display keeps one per camera since that's how the data already arrives)."""

    def __init__(self):
        self._tracks: dict[str, _TrackState] = {}

    def update(self, tracks: list[dict], now: float | None = None) -> None:
        now = now if now is not None else time.time()
        seen_ids = set()
        for t in tracks:
            tid = t["track_id"]
            seen_ids.add(tid)
            cx = (t["x1"] + t["x2"]) / 2
            cy = (t["y1"] + t["y2"]) / 2
            state = self._tracks.get(tid)
            if state is None:
                state = _TrackState(first_seen=now)
                self._tracks[tid] = state
            state.points.append((cx, cy, now))
            state.points = [(x, y, ts) for x, y, ts in state.points if now - ts <= TRAIL_WINDOW_S]

        # drop tracks that vanished (no bookkeeping needed for departure - trails just stop
        # growing and age out of rendering once every point exceeds TRAIL_WINDOW_S)
        stale = [tid for tid, s in self._tracks.items()
                 if s.points and now - s.points[-1][2] > TRAIL_WINDOW_S]
        for tid in stale:
            del self._tracks[tid]

    def trail(self, track_id: str, now: float | None = None) -> list[tuple[float, float, float]]:
        """[(x, y, alpha)] oldest-to-newest, alpha fading from 0 to 1."""
        now = now if now is not None else time.time()
        state = self._tracks.get(track_id)
        if state is None:
            return []
        return [(x, y, max(0.0, 1.0 - (now - ts) / TRAIL_WINDOW_S)) for x, y, ts in state.points]

    def pulse_alpha(self, track_id: str, now: float | None = None) -> float:
        """0 if not a recently-appeared track, fading 1 -> 0 over PULSE_DURATION_S if it is."""
        now = now if now is not None else time.time()
        state = self._tracks.get(track_id)
        if state is None:
            return 0.0
        age = now - state.first_seen
        if age >= PULSE_DURATION_S:
            return 0.0
        return 1.0 - age / PULSE_DURATION_S

    def active_track_ids(self) -> set[str]:
        return set(self._tracks.keys())
