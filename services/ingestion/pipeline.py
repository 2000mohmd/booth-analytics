"""Per-camera frame loop: detect -> track -> staff-filter -> zone/dwell update -> event store.

Each overhead camera runs this loop in its own thread against its own ZoneMap (pixel
coordinates are camera-local - see services/metrics_engine/zones.py) but all of them share one
VisitTracker instance, which is the actual multi-camera fusion point: it doesn't care how many
cameras feed it, only that each gives it a per-camera-namespaced track_id and a resolved zone
name. A stub row is inserted the moment a track appears (via VisitTracker's on_track_created
callback, wired in services/ingestion/main.py) and finalize_visit() fills in the rest when the
track disappears. Eye-level camera only samples demographics for tracks already marked as
active stoppers - see attribute_demographics() below.
"""
import logging
import os
import threading
import time

import cv2

from services.metrics_engine import store
from services.metrics_engine.dwell import VisitTracker
from services.metrics_engine.zones import ZoneMap
from services.perception.detector import PersonDetector
from services.perception.staff_filter import is_staff
from services.perception.tracker import PersonTracker

log = logging.getLogger(__name__)

RECONNECT_MAX_ATTEMPTS = 10
RECONNECT_BACKOFF_S = 2.0


def _reconnect(cap: cv2.VideoCapture, source: str | int, camera_id: str) -> cv2.VideoCapture:
    """RTSP sessions (NVR reboot, network blip, NVR's own concurrent-stream cap) drop
    without warning in real deployments - cv2.VideoCapture doesn't recover on its own, so a
    single dropped frame used to kill the camera thread for good. Retries opening a fresh
    VideoCapture with backoff instead of giving up after one failed read."""
    cap.release()
    for attempt in range(1, RECONNECT_MAX_ATTEMPTS + 1):
        log.warning("camera %s: read failed, reconnecting (attempt %d/%d)",
                    camera_id, attempt, RECONNECT_MAX_ATTEMPTS)
        time.sleep(RECONNECT_BACKOFF_S)
        cap = cv2.VideoCapture(source)
        if cap.isOpened():
            ok, _ = cap.read()
            if ok:
                log.info("camera %s: reconnected", camera_id)
                return cap
        cap.release()
    raise RuntimeError(f"camera {camera_id}: gave up reconnecting to {source} after "
                        f"{RECONNECT_MAX_ATTEMPTS} attempts")


class LatestFrameReader:
    """Drains a camera source on its own thread and keeps only the newest frame.

    cv2.VideoCapture buffers internally, and a detection tick takes far longer than one frame
    interval on CPU - reading once per tick made that buffer fall further behind real time
    until the RTSP session errored out. Draining continuously keeps processing on current
    frames regardless of how slow detection is."""

    def __init__(self, source: str | int, camera_id: str):
        self.source = source
        self.camera_id = camera_id
        self._cap = cv2.VideoCapture(source)
        if not self._cap.isOpened():
            raise RuntimeError(f"could not open camera source: {source}")
        self._cond = threading.Condition()
        self._frame = None
        self._seq = 0
        self._error: Exception | None = None
        self._stopped = False
        threading.Thread(target=self._run, daemon=True, name=f"reader-{camera_id}").start()

    def _run(self):
        try:
            while not self._stopped:
                ok, frame = self._cap.read()
                if not ok:
                    self._cap = _reconnect(self._cap, self.source, self.camera_id)
                    continue
                with self._cond:
                    self._frame = frame
                    self._seq += 1
                    self._cond.notify_all()
        except Exception as e:
            with self._cond:
                self._error = e
                self._cond.notify_all()
        finally:
            self._cap.release()

    def next_frame(self, after_seq: int, timeout: float = 30.0):
        """Newest frame with a sequence number past after_seq -> (seq, frame)."""
        with self._cond:
            if not self._cond.wait_for(lambda: self._seq > after_seq or self._error, timeout):
                raise RuntimeError(f"camera {self.camera_id}: no new frame in {timeout}s")
            if self._error:
                raise self._error
            return self._seq, self._frame

    def latest(self):
        with self._cond:
            return self._frame

    def stop(self):
        self._stopped = True


def _draw_tracks(frame, tracks):
    for t in tracks:
        cv2.rectangle(frame, (int(t["x1"]), int(t["y1"])), (int(t["x2"]), int(t["y2"])), (0, 255, 0), 2)
        cv2.putText(frame, f"id={t['track_id']}", (int(t["x1"]), int(t["y1"]) - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)


def _publish_debug_video(reader: LatestFrameReader, camera_id: str, conn, latest_tracks: dict, stop: threading.Event):
    """Encodes the newest frame with the most recent detection's boxes at a steady rate,
    independent of how long detection takes - video stays live even when boxes lag a bit."""
    while not stop.wait(DEBUG_VIDEO_SAMPLE_EVERY_S):
        frame = reader.latest()
        if frame is None:
            continue
        frame = frame.copy()
        _draw_tracks(frame, latest_tracks.get("rows", []))
        if frame.shape[1] > DEBUG_VIDEO_MAX_WIDTH:
            scale = DEBUG_VIDEO_MAX_WIDTH / frame.shape[1]
            frame = cv2.resize(frame, (DEBUG_VIDEO_MAX_WIDTH, int(frame.shape[0] * scale)))
        ok_enc, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok_enc:
            store.set_live_debug_frame(conn, camera_id, time.time(), buf.tobytes())


TRACK_GRACE_SECONDS = 3.5       # how long a track may be unseen before its visit is finalized -
# must stay >= PersonTracker's lost_track_buffer_seconds (see services/perception/tracker.py),
# or VisitTracker would finalize (and pop) a track's visit before ByteTrack gives up trying to
# re-associate it - so a successful re-association would look like a brand-new track_id here
# even though the numeric ID ByteTrack assigned was actually unchanged.
OCCUPANCY_SAMPLE_EVERY_S = 5.0
# Detection cap per overhead camera. Without it each loop runs YOLO on every frame as fast as the
# CPU/GPU allows, pinning the machine; dwell/zone analytics don't need more than a few fps.
# Calibration knob: raise via MAX_FPS if tracks fragment on fast walkers, lower on a weak laptop.
MAX_FPS = float(os.environ.get("MAX_FPS", "4"))
DEMOGRAPHICS_SAMPLE_EVERY_S = 2.0  # only sample the eye-level stream this often - stoppers dwell
LIVE_TRACK_SAMPLE_EVERY_S = 0.2   # debug live-track view refresh rate - bbox/zone numbers only,
# never the frame itself (services/metrics_engine/store.py's live_tracks table docstring)
DEBUG_VIDEO_SAMPLE_EVERY_S = 0.2  # only used when debug_video_stream=True (on by default for
# overhead cameras - see main.py) - powers the kiosk display (services/kiosk_display) and the
# dashboard's /live debug page. See live_debug_frames table docstring in
# services/metrics_engine/store.py for why this is a deliberate exception to the "no raw video"
# rule elsewhere in this project, scoped to overhead cameras only, never the eye-level camera.
DEBUG_VIDEO_MAX_WIDTH = 960        # downscale before JPEG-encoding - full 2560x1440 frames every
# tick is wasteful bandwidth/CPU for a feature that only needs to look right on a kiosk screen


def attribute_demographics(active_stopper_visit_ids: list[str], faces: list) -> str | None:
    """Which visit (if any) a set of detected faces should be attributed to this tick.

    v1 has no cross-camera re-id, so this only attributes when there's exactly one active
    stopper AND exactly one face in frame - anything more is ambiguous and gets skipped
    rather than guessed. See the cross-camera limitation note in README.md.
    """
    if len(active_stopper_visit_ids) == 1 and len(faces) == 1:
        return active_stopper_visit_ids[0]
    return None


def run_overhead_camera(
    camera_id: str,
    source: str | int,
    detector: PersonDetector,
    tracker: PersonTracker,
    zone_map: ZoneMap,
    visit_tracker: VisitTracker,
    conn,
    marker_config: dict,
    debug_preview: bool = False,
    debug_video_stream: bool = False,
    face_detector=None,
    face_embedder=None,
    demographics_classifier=None,
):
    """One of possibly several overhead cameras, each covering its own section of a booth too
    large for one camera's FOV. `tracker` and `zone_map` must be this camera's own instances
    (ByteTrack state and pixel coordinates are both camera-local); `visit_tracker` is shared
    across all overhead cameras for this booth - see the module docstring.

    debug_video_stream (DEBUG_VIDEO_STREAM=1 env var, see main.py) writes downscaled JPEG
    frames with box overlays to live_debug_frames for the dashboard's local-only debug video
    page - a deliberate, opt-in exception to this project's normal "no raw video leaves
    ingestion" rule (see that table's docstring). Off by default.

    face_detector/face_embedder/demographics_classifier are optional - given only for
    single-camera booths with no separate eye-level stream (see services/ingestion/main.py).
    When set, this loop runs face detection on its own frame each tick: the resulting per-track
    embedding lets VisitTracker catch same-camera duplicate tracks (see dwell.py's module
    docstring), and demographics attach directly to the track a face spatially belongs to -
    no single-stopper/single-face ambiguity to resolve, unlike run_eyelevel_camera's path,
    since here the face-to-track mapping is unambiguous by construction.
    """
    reader = LatestFrameReader(source, camera_id)
    latest_tracks: dict = {"rows": []}
    stop_publisher = threading.Event()
    if debug_video_stream:
        threading.Thread(
            target=_publish_debug_video, args=(reader, camera_id, conn, latest_tracks, stop_publisher),
            daemon=True, name=f"debug-video-{camera_id}",
        ).start()

    last_sample = 0.0
    last_demographics_sample = 0.0
    last_live_track_sample = 0.0
    seq = 0
    next_tick = 0.0
    try:
        while True:
            if (wait := next_tick - time.time()) > 0:
                time.sleep(wait)
            next_tick = time.time() + 1.0 / MAX_FPS
            seq, frame = reader.next_frame(seq)
            frame = frame.copy()

            now = time.time()
            detections = detector.detect(frame)
            tracks = tracker.update(detections, frame)

            track_faces, track_embeddings = {}, {}
            if face_detector is not None and tracks:
                for crop, (fx1, fy1, fx2, fy2) in face_detector.detect_faces_with_boxes(frame):
                    fcx, fcy = (fx1 + fx2) / 2, (fy1 + fy2) / 2
                    for t in tracks:
                        if t.x1 <= fcx <= t.x2 and t.y1 <= fcy <= t.y2:
                            track_faces[t.track_id] = crop
                            if face_embedder is not None:
                                track_embeddings[t.track_id] = face_embedder.embed(crop)
                            break

            sample_demographics = (
                demographics_classifier is not None
                and now - last_demographics_sample >= DEMOGRAPHICS_SAMPLE_EVERY_S
            )

            live_track_rows = []
            for t in tracks:
                crop = frame[int(t.y1):int(t.y2), int(t.x1):int(t.x2)]
                staff = is_staff(crop, marker_config)
                cx, cy = t.centroid
                zone = zone_map.zone_for_point(cx, cy)
                namespaced_id = f"{camera_id}:{t.track_id}"
                visit_tracker.update(
                    namespaced_id, camera_id, zone, cx, cy, now, is_staff=staff,
                    face_embedding=track_embeddings.get(t.track_id),
                )
                if sample_demographics and not staff and t.track_id in track_faces:
                    visit_id = visit_tracker.visit_id_for(namespaced_id)
                    if visit_id is not None:
                        estimate = demographics_classifier.estimate(track_faces[t.track_id])
                        store.update_visit_demographics(
                            conn, visit_id, estimate.gender, estimate.gender_conf,
                            estimate.age_bracket, estimate.age_conf,
                        )
                if not staff:
                    live_track_rows.append({
                        "track_id": t.track_id, "x1": t.x1, "y1": t.y1, "x2": t.x2, "y2": t.y2,
                        "zone": zone,
                    })
            if sample_demographics:
                last_demographics_sample = now
            latest_tracks["rows"] = live_track_rows

            if now - last_live_track_sample >= LIVE_TRACK_SAMPLE_EVERY_S:
                store.replace_live_tracks(conn, camera_id, now, frame.shape[1], frame.shape[0], live_track_rows)
                last_live_track_sample = now

            for visit in visit_tracker.expire_stale(now, TRACK_GRACE_SECONDS):
                store.finalize_visit(conn, visit)

            if now - last_sample >= OCCUPANCY_SAMPLE_EVERY_S:
                from services.metrics_engine.occupancy import sample_occupancy

                sample_occupancy(conn, visit_tracker.booth_id, visit_tracker)
                last_sample = now

            if debug_preview:
                _draw_tracks(frame, live_track_rows)
                cv2.imshow(f"overhead debug: {camera_id}", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        stop_publisher.set()
        reader.stop()
        if debug_preview:
            cv2.destroyAllWindows()
        store.replace_live_tracks(conn, camera_id, time.time(), 0, 0, [])
        # flush any still-active tracks so we don't lose partial visits on shutdown
        now = time.time()
        for visit in visit_tracker.expire_stale(now, grace_seconds=-1):
            store.finalize_visit(conn, visit)


def run_eyelevel_camera(source: str | int, face_detector, demographics_classifier, visit_tracker, conn):
    """Runs in its own process alongside run_overhead_camera (see services/ingestion/main.py's
    two entrypoints). Only samples every DEMOGRAPHICS_SAMPLE_EVERY_S - stoppers dwell for
    seconds, running face detection every frame would burn compute for no accuracy gain.
    """
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"could not open camera source: {source}")

    last_sample = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                cap = _reconnect(cap, source, "eyelevel")
                continue

            now = time.time()
            if now - last_sample < DEMOGRAPHICS_SAMPLE_EVERY_S:
                continue
            last_sample = now

            active_stoppers = visit_tracker.active_stopper_visit_ids(now)
            if not active_stoppers:
                continue

            faces = face_detector.detect_faces(frame)
            visit_id = attribute_demographics(active_stoppers, faces)
            if visit_id is None:
                continue

            estimate = demographics_classifier.estimate(faces[0])
            store.update_visit_demographics(
                conn, visit_id, estimate.gender, estimate.gender_conf,
                estimate.age_bracket, estimate.age_conf,
            )
    finally:
        cap.release()
