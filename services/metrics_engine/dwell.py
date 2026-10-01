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

Cross-camera re-identification: `zone_transitions` (see configs/booth.example.yaml) declares
which (camera, zone) pairs are physically adjacent, e.g. two overhead cameras' "aisle" zones
meeting at the section boundary. When a track disappears from a zone that's the near side of a
configured transition, it's held as a *pending handoff* for that transition's max_gap_seconds
instead of being finalized immediately; if a brand-new track then appears in the paired (camera,
zone) within that window, it adopts the pending track's visit_id/history rather than starting a
new visit. This only re-identifies a visitor crossing a *declared* boundary within the configured
time window, and a wrong/missing zone_transitions entry silently falls back to the old
two-visits behavior rather than erroring.

Same-camera duplicate tracks: a single physical person can still get *two simultaneous* track
IDs from one camera - not a hand-off, a genuine double detection (YOLO producing two overlapping
boxes for one body that ByteTrack then tracks as separate objects). Zone transitions can't catch
this since both tracks are on the same camera at the same time. If callers pass a face
`face_embedding` per update() (see services/perception/face_id.py and pipeline.py's inline
face-id path for single-camera booths), a brand-new track whose face closely matches an
*already-active* track's most recent face is treated as the same person - the new track_id is
aliased to the existing one instead of minting a second visit.
"""
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _iso(epoch_ts: float) -> str:
    return datetime.fromtimestamp(epoch_ts, tz=timezone.utc).isoformat()

PASSTHROUGH_ZONE = "aisle"
POSITION_TRACE_STRIDE = 5  # keep every Nth point - heatmap doesn't need full-rate traces

CameraZone = tuple[str, str]  # (camera_id, zone_name)
ZoneTransition = tuple[CameraZone, CameraZone, float]  # (from, to, max_gap_seconds)


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
    position_trace: list[tuple[str, int, int]] = field(default_factory=list)  # (camera_id, x, y)
    frame_count: int = 0


class VisitTracker:
    def __init__(self, booth_id: str, stopper_threshold_s: float, on_track_created=None,
                 zone_transitions: list[ZoneTransition] | None = None,
                 face_match_threshold: float = 0.45, face_reacquire_seconds: float = 5.0):
        """on_track_created(visit_stub: dict), if given, fires the moment a new track appears -
        so the caller can insert a row immediately. Demographics may get attached to this
        visit_id while the track is still active (see active_stopper_visit_ids()), well before
        finalize() runs, so a row needs to exist before then - see store.finalize_visit().

        zone_transitions declares adjacent (camera, zone) pairs for cross-camera re-id (see
        module docstring) - each entry is treated as bidirectional, since a visitor can cross a
        booth-section boundary in either direction.

        face_match_threshold is the minimum cosine similarity (embeddings are unit-normalized,
        so this is just a dot product) for two face embeddings to be considered the same person
        for same-camera duplicate/reacquire detection - see module docstring. 0.45 is deliberately
        loose to favor merging over double-counting, given the embeddings aren't from aligned
        crops (see services/perception/face_id.py); tune per-deployment if it merges genuinely
        different people too eagerly.

        face_reacquire_seconds is how long a track with a known face is held pending (not yet
        finalized) after going stale, in case a new track with a matching face appears - this is
        what actually fixes sequential fragmentation (ByteTrack loses and reacquires a person a
        moment later under a new ID), as opposed to _find_duplicate_active_track's simultaneous
        double-detection case."""
        self.booth_id = booth_id
        self.stopper_threshold_s = stopper_threshold_s
        self.on_track_created = on_track_created
        self.face_match_threshold = face_match_threshold
        self.face_reacquire_seconds = face_reacquire_seconds
        self._tracks: dict[str, _TrackState] = {}
        self._transitions: dict[CameraZone, list[tuple[str, str, float]]] = {}
        for from_cz, to_cz, max_gap in zone_transitions or []:
            self._transitions.setdefault(from_cz, []).append((*to_cz, max_gap))
            self._transitions.setdefault(to_cz, []).append((*from_cz, max_gap))
        # tracks that vanished from a zone_transitions "near side", or that simply had a known
        # face, held here instead of being finalized immediately in case a new track claims them
        # (a cross-camera continuation, or a same-camera face-based reacquire - see module
        # docstring). Keyed by original track_id; value is (claim_deadline, state, embedding).
        self._pending_handoffs: dict[str, tuple[float, _TrackState, object]] = {}
        # duplicate-track_id -> real track_id it was aliased to (see module docstring); and each
        # real (non-aliased) track_id's most recent face embedding, for matching against.
        self._aliases: dict[str, str] = {}
        self._active_faces: dict[str, object] = {}
        # multiple overhead cameras' threads all call update()/expire_stale() on this same
        # instance - RLock (not Lock) because expire_stale() calls finalize() internally while
        # already holding it.
        self._lock = threading.RLock()

    def _all_states(self) -> list[_TrackState]:
        return list(self._tracks.values()) + [s for _, s, _ in self._pending_handoffs.values()]

    def active_count(self, exclude_staff: bool = True) -> int:
        with self._lock:
            return sum(1 for t in self._all_states() if not (exclude_staff and t.is_staff))

    def staff_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._all_states() if t.is_staff)

    def _claim_pending_handoff(
        self, camera_id: str, zone: str | None, ts: float, face_embedding=None,
    ) -> _TrackState | None:
        """A brand-new track just appeared at (camera_id, zone), maybe with a face embedding -
        see if it's the continuation of a track that recently vanished, either on the other side
        of a configured zone transition, or (same camera) with a closely matching face."""
        best_id, best_state, best_sim = None, None, self.face_match_threshold
        for track_id, (deadline, state, pending_embedding) in self._pending_handoffs.items():
            if ts > deadline:
                continue
            if face_embedding is not None and pending_embedding is not None:
                sim = float(sum(a * b for a, b in zip(face_embedding, pending_embedding)))
                if sim >= best_sim:
                    best_id, best_state, best_sim = track_id, state, sim
                    continue
            if zone is not None:
                allowed = self._transitions.get((state.camera_id, state.current_zone), [])
                if any(dest_cam == camera_id and dest_zone == zone for dest_cam, dest_zone, _ in allowed):
                    best_id, best_state = track_id, state
                    break  # zone-transition matches are exact, not a similarity ranking
        if best_id is not None:
            del self._pending_handoffs[best_id]
        return best_state

    def _find_duplicate_active_track(self, embedding, exclude_track_id: str) -> str | None:
        """A brand-new track just appeared with a face embedding - check whether it's actually a
        second, spurious detection of someone we're *already* tracking on this tick, rather than
        a genuinely new person. See module docstring."""
        best_id, best_sim = None, self.face_match_threshold
        for real_id, known_embedding in self._active_faces.items():
            if real_id == exclude_track_id or real_id not in self._tracks:
                continue
            sim = float(sum(a * b for a, b in zip(embedding, known_embedding)))
            if sim >= best_sim:
                best_id, best_sim = real_id, sim
        return best_id

    def update(self, track_id: str, camera_id: str, zone: str | None, x: float, y: float,
               ts: float, is_staff: bool = False, face_embedding=None):
        """track_id must already be namespaced per-camera by the caller (see module docstring).
        zone is resolved by the caller's own ZoneMap - this class doesn't do coordinate math.
        face_embedding is optional (see module docstring's same-camera duplicate-track note)."""
        with self._lock:
            track_id = self._aliases.get(track_id, track_id)
            state = self._tracks.get(track_id)

            if state is None and face_embedding is not None:
                dup_id = self._find_duplicate_active_track(face_embedding, track_id)
                if dup_id is not None:
                    self._aliases[track_id] = dup_id
                    track_id = dup_id
                    state = self._tracks[track_id]

            if state is None:
                state = self._claim_pending_handoff(camera_id, zone, ts, face_embedding)
                if state is not None:
                    # continuing an existing visit under a new (camera-local) track_id - no
                    # on_track_created callback, the visit row already exists from before.
                    if zone != state.current_zone:
                        self._accumulate_dwell(state, ts)
                        state.current_zone = zone
                        state.zone_entered_at = ts
                        if zone:
                            state.zone_path.append(zone)
                else:
                    state = _TrackState(
                        visit_id=str(uuid.uuid4()), entered_at=ts, is_staff=is_staff, camera_id=camera_id,
                        last_seen=ts, current_zone=zone, zone_entered_at=ts,
                    )
                    if zone:
                        state.zone_path.append(zone)
                    if self.on_track_created:
                        self.on_track_created(self._stub(state))
                self._tracks[track_id] = state
            else:
                state.is_staff = state.is_staff or is_staff
                if zone != state.current_zone:
                    self._accumulate_dwell(state, ts)
                    state.current_zone = zone
                    state.zone_entered_at = ts
                    if zone:
                        state.zone_path.append(zone)

            state.camera_id = camera_id
            state.last_seen = ts
            state.frame_count += 1
            if state.frame_count % POSITION_TRACE_STRIDE == 0:
                state.position_trace.append((camera_id, round(x), round(y)))
            if face_embedding is not None:
                self._active_faces[track_id] = face_embedding

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
        """Each point is stored with the camera_id it was captured under, so a point's (x,y) is
        never read against the wrong camera's pixel space. Grouped into 'camera|x,y;x,y' segments
        (one per camera the visit passed through, in order) and joined with '/' - a visit
        re-identified across a zone transition has more than one segment; everyone else has
        exactly one, same as before this feature existed."""
        segments = []
        current_cam, current_pts = None, []
        for cam, x, y in state.position_trace:
            if cam != current_cam:
                if current_cam is not None:
                    segments.append((current_cam, current_pts))
                current_cam, current_pts = cam, []
            current_pts.append((x, y))
        segments.append((current_cam if current_cam is not None else state.camera_id, current_pts))
        return "/".join(f"{cam}|" + ";".join(f"{x},{y}" for x, y in pts) for cam, pts in segments)

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

    def visit_id_for(self, track_id: str) -> str | None:
        """The current visit_id a (possibly-aliased, see module docstring) track_id maps to, or
        None if it's not currently tracked. Used by the inline face-id path in
        services/ingestion/pipeline.py to attach demographics directly to the right visit
        without the separate eye-level path's single-stopper/single-face ambiguity."""
        with self._lock:
            state = self._tracks.get(self._aliases.get(track_id, track_id))
            return state.visit_id if state else None

    def active_stopper_visit_ids(self, now: float) -> list[str]:
        """visit_ids of non-staff tracks currently dwelling >= threshold in a stop zone.
        Used by the eye-level camera loop to attribute a demographics estimate to a visit -
        see services/ingestion/pipeline.py's attribute_demographics()."""
        with self._lock:
            return [
                s.visit_id for s in self._all_states()
                if not s.is_staff and self._live_dwell_seconds(s, now) >= self.stopper_threshold_s
            ]

    def _forget(self, track_id: str) -> None:
        """Drop a no-longer-active track's face bookkeeping (see _find_duplicate_active_track) -
        called wherever a track_id is popped from self._tracks, so a finalized visit's old face
        can never be matched against again, and its alias entries don't leak."""
        self._active_faces.pop(track_id, None)
        for alias_id, real_id in list(self._aliases.items()):
            if real_id == track_id:
                del self._aliases[alias_id]

    def expire_stale(self, now: float, grace_seconds: float) -> list[dict]:
        """Finalize and return visit rows for tracks not seen within grace_seconds. Safe to call
        from every camera's thread - a track only ever gets finalized once even if two threads'
        loops both notice it's stale around the same tick, since the whole scan-and-pop happens
        under one lock.

        A negative grace_seconds means "flush everything now" (shutdown) - used by
        services/ingestion/pipeline.py to avoid losing in-progress visits on exit. In that case
        pending cross-camera handoffs are finalized immediately too, rather than waiting out
        their claim window, since no other camera thread is still running to claim them."""
        with self._lock:
            finalized = []
            stale_ids = [tid for tid, s in self._tracks.items() if now - s.last_seen > grace_seconds]
            for tid in stale_ids:
                state = self._tracks.pop(tid)
                known_face = self._active_faces.get(tid)
                self._forget(tid)
                transitions = self._transitions.get((state.camera_id, state.current_zone), [])
                hold_seconds = max(
                    max((gap for _, _, gap in transitions), default=0.0),
                    self.face_reacquire_seconds if known_face is not None else 0.0,
                )
                if hold_seconds > 0 and grace_seconds >= 0:
                    self._pending_handoffs[tid] = (state.last_seen + hold_seconds, state, known_face)
                else:
                    finalized.append(self._finalize_state(state, state.last_seen))

            flush_all_pending = grace_seconds < 0
            expired = [
                tid for tid, (deadline, _, _) in self._pending_handoffs.items()
                if flush_all_pending or now > deadline
            ]
            for tid in expired:
                _, state, _ = self._pending_handoffs.pop(tid)
                finalized.append(self._finalize_state(state, state.last_seen))

            return finalized

    def finalize(self, track_id: str, exited_at: float) -> dict:
        with self._lock:
            state = self._tracks.pop(track_id)
            self._forget(track_id)
            return self._finalize_state(state, exited_at)

    def _finalize_state(self, state: _TrackState, exited_at: float) -> dict:
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
