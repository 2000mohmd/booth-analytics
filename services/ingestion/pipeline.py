"""Per-camera frame loop: detect -> track -> staff-filter -> zone/dwell update -> event store.

Overhead camera drives counting/dwell/zones (authoritative) and owns the visits table row
lifecycle: a stub row is inserted the moment a track appears (via VisitTracker's
on_track_created callback, wired in services/ingestion/main.py) and finalize_visit() fills in
the rest when the track disappears. Eye-level camera only samples demographics for tracks
already marked as active stoppers - see attribute_demographics() below.
"""
import logging
import time

import cv2

from services.metrics_engine import store
from services.metrics_engine.dwell import VisitTracker
from services.perception.detector import PersonDetector
from services.perception.staff_filter import is_staff
from services.perception.tracker import PersonTracker

log = logging.getLogger(__name__)

TRACK_GRACE_SECONDS = 2.0       # how long a track may be unseen before its visit is finalized
OCCUPANCY_SAMPLE_EVERY_S = 5.0
DEMOGRAPHICS_SAMPLE_EVERY_S = 2.0  # only sample the eye-level stream this often - stoppers dwell


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
    source: str | int,
    detector: PersonDetector,
    tracker: PersonTracker,
    visit_tracker: VisitTracker,
    conn,
    marker_config: dict,
    debug_preview: bool = False,
):
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"could not open camera source: {source}")

    last_sample = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            now = time.time()
            detections = detector.detect(frame)
            tracks = tracker.update(detections, frame)

            for t in tracks:
                crop = frame[int(t.y1):int(t.y2), int(t.x1):int(t.x2)]
                staff = is_staff(crop, marker_config)
                cx, cy = t.centroid
                visit_tracker.update(str(t.track_id), cx, cy, now, is_staff=staff)

            for visit in visit_tracker.expire_stale(now, TRACK_GRACE_SECONDS):
                store.finalize_visit(conn, visit)

            if now - last_sample >= OCCUPANCY_SAMPLE_EVERY_S:
                from services.metrics_engine.occupancy import sample_occupancy

                sample_occupancy(conn, visit_tracker.booth_id, visit_tracker)
                last_sample = now

            if debug_preview:
                for t in tracks:
                    cv2.rectangle(frame, (int(t.x1), int(t.y1)), (int(t.x2), int(t.y2)), (0, 255, 0), 2)
                    cv2.putText(frame, f"id={t.track_id}", (int(t.x1), int(t.y1) - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                cv2.imshow("overhead debug", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        cap.release()
        if debug_preview:
            cv2.destroyAllWindows()
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
                break

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
