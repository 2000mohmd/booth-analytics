"""Per-track zone/dwell bookkeeping. One VisitTracker per booth, shared across every overhead
camera - each camera resolves zones in its own pixel coordinates (see services/metrics_engine/
zones.py) and passes the resolved zone *name* in here, so this class never needs to know how
many cameras exist or what coordinate space any of them are in. Call update() every frame,
finalize() when a track has been missing longer than the configured grace period.

Dwell is time spent in any zone other than 'aisle' (the passthrough/counting zone) - that's
what the build plan means by "stoppers (dwell >= threshold in stand/table zone)".

Track IDs are only unique per camera (ByteTrack numbers them 1, 2, 3... per stream) - callers
MUST namespace them (e.g. f"{camera_id}:{track_id}") before calling update(), or two cameras'
tracks will collide in here. See services/ingestion/pipeline.py.

Multi-camera limitation: there's no cross-camera re-identification. A visitor who physically
walks from one camera's coverage area into another's is counted as two separate visits, not
one continuous one. Fine when each camera covers a non-overlapping section of a large booth
and visitors don't move between sections mid-visit; not fine if they do. No re-id model in v1.
"""
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _iso(epoch_ts: float) -> str:
    return datetime.fromtimestamp(epoch_ts, tz=timezone.utc).isoformat()

PASSTHROUGH_ZONE = "aisle"
POSITION_TRACE_STRIDE = 5  # keep every Nth point - heatmap doesn't need full-rate traces


@dataclass
class _TrackState:
    visit_id: str
    entered_at: float
    is_staff: bool
    last_seen: float
    camera_id: str
    current_zone: str | None = None
    zone_entered_at: float = 0.0
    zone_path: list[str] = field(default_factory=list)
    dwell_seconds: float = 0.0
    position_trace: list[tuple[int, int]] = field(default_factory=list)
    frame_count: int = 0


class VisitTracker:
    def __init__(self, booth_id: str, stopper_threshold_s: float, on_track_created=None):
        """on_track_created(visit_stub: dict), if given, fires the moment a new track appears -
        so the caller can insert a row immediately. Demographics may get attached to this
        visit_id while the track is still active (see active_stopper_visit_ids()), well before
        finalize() runs, so a row needs to exist before then - see store.finalize_visit()."""
        self.booth_id = booth_id
        self.stopper_threshold_s = stopper_threshold_s
        self.on_track_created = on_track_created
        self._tracks: dict[str, _TrackState] = {}
        # multiple overhead cameras' threads all call update()/expire_stale() on this same
        # instance - RLock (not Lock) because expire_stale() calls finalize() internally while
        # already holding it.
        self._lock = threading.RLock()

    def active_count(self, exclude_staff: bool = True) -> int:
        with self._lock:
            return sum(1 for t in self._tracks.values() if not (exclude_staff and t.is_staff))

    def staff_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._tracks.values() if t.is_staff)

    def update(self, track_id: str, camera_id: str, zone: str | None, x: float, y: float,
               ts: float, is_staff: bool = False):
        """track_id must already be namespaced per-camera by the caller (see module docstring).
        zone is resolved by the caller's own ZoneMap - this class doesn't do coordinate math."""
        with self._lock:
            state = self._tracks.get(track_id)

            if state is None:
                state = _TrackState(
                    visit_id=str(uuid.uuid4()), entered_at=ts, is_staff=is_staff, camera_id=camera_id,
                    last_seen=ts, current_zone=zone, zone_entered_at=ts,
                )
                if zone:
                    state.zone_path.append(zone)
                self._tracks[track_id] = state
                if self.on_track_created:
                    self.on_track_created(self._stub(state))
            else:
                state.is_staff = state.is_staff or is_staff
                if zone != state.current_zone:
                    self._accumulate_dwell(state, ts)
                    state.current_zone = zone
                    state.zone_entered_at = ts
                    if zone:
                        state.zone_path.append(zone)

            state.last_seen = ts
            state.frame_count += 1
            if state.frame_count % POSITION_TRACE_STRIDE == 0:
                state.position_trace.append((round(x), round(y)))

    def _stub(self, state: _TrackState) -> dict:
        """Initial row for a just-created track - insert_visit() writes this immediately so
        finalize_visit()'s later UPDATE (and any demographics UPDATE in between) has a row."""
        return {
            "visit_id": state.visit_id, "booth_id": self.booth_id, "entered_at": _iso(state.entered_at),
            "exited_at": None, "zone_path": "→".join(state.zone_path), "dwell_seconds": 0.0,
            "is_stopper": False, "is_staff": state.is_staff, "gender_est": None, "gender_conf": None,
            "age_bracket": None, "age_conf": None, "position_trace": f"{state.camera_id}|",
        }

    def _format_trace(self, state: _TrackState) -> str:
        """camera_id prefix so a point's (x,y) is never read against the wrong camera's pixel
        space - every point in one track's trace is from the same camera (tracks don't migrate
        cameras, see module docstring), but different visits in the DB come from different ones."""
        points = ";".join(f"{x},{y}" for x, y in state.position_trace)
        return f"{state.camera_id}|{points}"

    def _accumulate_dwell(self, state: _TrackState, ts: float):
        if state.current_zone and state.current_zone != PASSTHROUGH_ZONE:
            state.dwell_seconds += ts - state.zone_entered_at

    def _live_dwell_seconds(self, state: _TrackState, now: float) -> float:
        """dwell_seconds accumulated so far plus time still accruing in the current zone -
        used to decide "is this track a stopper right now", not just at finalize()."""
        live = state.dwell_seconds
        if state.current_zone and state.current_zone != PASSTHROUGH_ZONE:
            live += now - state.zone_entered_at
        return live

    def active_stopper_visit_ids(self, now: float) -> list[str]:
        """visit_ids of non-staff tracks currently dwelling >= threshold in a stop zone.
        Used by the eye-level camera loop to attribute a demographics estimate to a visit -
        see services/ingestion/pipeline.py's attribute_demographics()."""
        with self._lock:
            return [
                s.visit_id for s in self._tracks.values()
                if not s.is_staff and self._live_dwell_seconds(s, now) >= self.stopper_threshold_s
            ]

    def expire_stale(self, now: float, grace_seconds: float) -> list[dict]:
        """Finalize and return visit rows for tracks not seen within grace_seconds. Safe to call
        from every camera's thread - a track only ever gets finalized once even if two threads'
        loops both notice it's stale around the same tick, since the whole scan-and-pop happens
        under one lock."""
        with self._lock:
            stale_ids = [tid for tid, s in self._tracks.items() if now - s.last_seen > grace_seconds]
            return [self.finalize(tid, self._tracks[tid].last_seen) for tid in stale_ids]

    def finalize(self, track_id: str, exited_at: float) -> dict:
        with self._lock:
            state = self._tracks.pop(track_id)
            self._accumulate_dwell(state, exited_at)
            return {
                "visit_id": state.visit_id,
                "booth_id": self.booth_id,
                "entered_at": _iso(state.entered_at),
                "exited_at": _iso(exited_at),
                "zone_path": "→".join(state.zone_path),
                "dwell_seconds": round(state.dwell_seconds, 2),
                "is_stopper": state.dwell_seconds >= self.stopper_threshold_s,
                "is_staff": state.is_staff,
                "gender_est": None,
                "gender_conf": None,
                "age_bracket": None,
                "age_conf": None,
                "position_trace": self._format_trace(state),
            }
