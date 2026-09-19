"""Per-track zone/dwell bookkeeping. One VisitTracker per booth; call update() every frame,
finalize() when a track has been missing longer than the configured grace period.

Dwell is time spent in any zone other than 'aisle' (the passthrough/counting zone) - that's
what the build plan means by "stoppers (dwell >= threshold in stand/table zone)".
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from services.metrics_engine.zones import ZoneMap


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
    current_zone: str | None = None
    zone_entered_at: float = 0.0
    zone_path: list[str] = field(default_factory=list)
    dwell_seconds: float = 0.0
    position_trace: list[tuple[int, int]] = field(default_factory=list)
    frame_count: int = 0


class VisitTracker:
    def __init__(self, booth_id: str, zone_map: ZoneMap, stopper_threshold_s: float, on_track_created=None):
        """on_track_created(visit_stub: dict), if given, fires the moment a new track appears -
        so the caller can insert a row immediately. Demographics may get attached to this
        visit_id while the track is still active (see active_stopper_visit_ids()), well before
        finalize() runs, so a row needs to exist before then - see store.finalize_visit()."""
        self.booth_id = booth_id
        self.zone_map = zone_map
        self.stopper_threshold_s = stopper_threshold_s
        self.on_track_created = on_track_created
        self._tracks: dict[str, _TrackState] = {}

    def active_count(self, exclude_staff: bool = True) -> int:
        return sum(1 for t in self._tracks.values() if not (exclude_staff and t.is_staff))

    def staff_count(self) -> int:
        return sum(1 for t in self._tracks.values() if t.is_staff)

    def update(self, track_id: str, x: float, y: float, ts: float, is_staff: bool = False):
        state = self._tracks.get(track_id)
        zone = self.zone_map.zone_for_point(x, y)

        if state is None:
            state = _TrackState(
                visit_id=str(uuid.uuid4()), entered_at=ts, is_staff=is_staff,
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
            "age_bracket": None, "age_conf": None, "position_trace": "",
        }

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
        return [
            s.visit_id for s in self._tracks.values()
            if not s.is_staff and self._live_dwell_seconds(s, now) >= self.stopper_threshold_s
        ]

    def expire_stale(self, now: float, grace_seconds: float) -> list[dict]:
        """Finalize and return visit rows for tracks not seen within grace_seconds."""
        finalized = []
        for track_id in [tid for tid, s in self._tracks.items() if now - s.last_seen > grace_seconds]:
            finalized.append(self.finalize(track_id, self._tracks[track_id].last_seen))
        return finalized

    def finalize(self, track_id: str, exited_at: float) -> dict:
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
            "position_trace": ";".join(f"{x},{y}" for x, y in state.position_trace),
        }
