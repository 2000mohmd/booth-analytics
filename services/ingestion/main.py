"""Camera ingestion entrypoint. Reads booth.yaml + models.yaml and runs every configured
camera's loop as a thread in one process - all overhead cameras and the eye-level camera
share one VisitTracker in memory, which is how (a) multiple overhead cameras fuse into one
counting/dwell ledger and (b) the eye-level loop knows which track is an active stopper right
now (see dwell.VisitTracker.active_stopper_visit_ids). A DB is the only channel between
separate processes/containers, and that state changes every frame, so this stays one process
per booth rather than one container per camera.
"""
import argparse
import logging
import os
import threading

from services.common.config import (
    DEFAULT_BOOTH_CONFIG,
    DEFAULT_DB_PATH,
    expand_env_placeholders,
    load_dotenv_if_present,
    load_yaml,
)
from services.metrics_engine import store
from services.metrics_engine.dwell import VisitTracker
from services.metrics_engine.zones import ZoneMap
from services.perception.detector import PersonDetector
from services.perception.tracker import PersonTracker

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ingestion")


def parse_zone_transitions(raw: list[dict] | None) -> list[tuple[tuple[str, str], tuple[str, str], float]]:
    """booth.yaml's zone_transitions (list of {from: {camera,zone}, to: {camera,zone},
    max_gap_seconds}) -> the (camera, zone) tuple form VisitTracker takes."""
    transitions = []
    for entry in raw or []:
        from_cz = (entry["from"]["camera"], entry["from"]["zone"])
        to_cz = (entry["to"]["camera"], entry["to"]["zone"])
        transitions.append((from_cz, to_cz, float(entry["max_gap_seconds"])))
    return transitions


def main():
    load_dotenv_if_present()

    parser = argparse.ArgumentParser()
    parser.add_argument("--booth-config", default=os.environ.get("BOOTH_CONFIG", DEFAULT_BOOTH_CONFIG))
    parser.add_argument("--models-config", default=os.environ.get("MODELS_CONFIG", "configs/models.yaml"))
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", DEFAULT_DB_PATH))
    parser.add_argument("--debug-preview", action="store_true")
    parser.add_argument("--debug-video-stream", dest="debug_video_stream",
                         action=argparse.BooleanOptionalAction,
                         default=os.environ.get("DEBUG_VIDEO_STREAM", "1") != "0",
                         help="streams downscaled JPEG frames (tracking boxes already drawn) "
                              "for overhead cameras only, to the kiosk display "
                              "(services/kiosk_display) and the dashboard's /live debug page. "
                              "On by default - this is the production marketing-kiosk video "
                              "feed, not a local-only debug toggle (see services/kiosk_display's "
                              "docs for why the eye-level camera never gets this regardless of "
                              "this flag - see pipeline.py's run_eyelevel_camera, which has no "
                              "such parameter at all). Set --no-debug-video-stream or "
                              "DEBUG_VIDEO_STREAM=0 to disable if the kiosk display isn't used.")
    parser.add_argument("--skip-demographics", action="store_true",
                         help="run overhead-only (counting/dwell/zones) without the eye-level face pipeline")
    args = parser.parse_args()

    booth = load_yaml(args.booth_config)
    for cam in booth["cameras"]:
        # source may be an int USB device index (e.g. 0) as well as an RTSP URL string -
        # only expand placeholders on strings, so a webcam index's type never changes.
        if isinstance(cam["source"], str):
            cam["source"] = expand_env_placeholders(cam["source"])
    models = load_yaml(args.models_config)
    device = "cuda" if models.get("execution_provider") == "CUDAExecutionProvider" else "cpu"

    overhead_cameras = [c for c in booth["cameras"] if c["role"] == "overhead"]
    if not overhead_cameras:
        raise ValueError("booth.yaml has no camera with role: overhead - need at least one")

    # one shared PersonDetector (see its class docstring for why sharing is safe/preferred),
    # one PersonTracker per camera (ByteTrack state is inherently per-stream, can't be shared)
    detector = PersonDetector(
        weights_path=models["detector"]["weights"],
        confidence_threshold=models["detector"]["confidence_threshold"], device=device,
    )
    conn = store.connect(args.db_path)
    visit_tracker = VisitTracker(
        booth_id=booth["booth_id"], stopper_threshold_s=booth["thresholds"]["dwell_seconds_stopper"],
        on_track_created=lambda stub: store.insert_visit(conn, stub),
        zone_transitions=parse_zone_transitions(booth.get("zone_transitions")),
    )

    from services.ingestion.pipeline import run_eyelevel_camera, run_overhead_camera

    eyelevel = next((c for c in booth["cameras"] if c["role"] == "eyelevel"), None)

    # Built once, shared however many places need them. With an eyelevel camera, they run in
    # that separate thread (run_eyelevel_camera) exactly as before. Without one - a
    # single-camera booth - they're handed to each overhead camera loop instead, which runs
    # face detection on its own frame: see pipeline.py's run_overhead_camera docstring for why
    # that's actually *less* ambiguous than the eyelevel path, not a lesser substitute for it.
    face_detector = demographics_classifier = face_embedder = None
    if not args.skip_demographics and "face_detector" in models and "demographics" in models:
        from services.perception.demographics import DemographicsClassifier, FaceDetector

        face_detector = FaceDetector(
            weights_path=models["face_detector"]["weights"],
            confidence_threshold=models["face_detector"]["confidence_threshold"],
        )
        demographics_classifier = DemographicsClassifier(
            weights_path=models["demographics"]["weights"],
            confidence_threshold=models["demographics"]["confidence_threshold"],
        )
        if "face_recognition" in models:
            from services.perception.face_id import FaceEmbedder

            face_embedder = FaceEmbedder(weights_path=models["face_recognition"]["weights"])

    threads = []
    for cam in overhead_cameras:
        zone_map = ZoneMap(cam.get("zones") or {})
        kwargs = dict(
            camera_id=cam["id"], source=cam["source"], detector=detector,
            tracker=PersonTracker(), zone_map=zone_map, visit_tracker=visit_tracker,
            conn=conn, marker_config=booth["staff_marker"], debug_preview=args.debug_preview,
            debug_video_stream=args.debug_video_stream,
        )
        if eyelevel is None and face_detector is not None:
            kwargs.update(face_detector=face_detector, face_embedder=face_embedder,
                          demographics_classifier=demographics_classifier)
        threads.append(threading.Thread(target=run_overhead_camera, kwargs=kwargs, daemon=True))
        log.info("configured overhead camera: id=%s source=%s zones=%s",
                  cam["id"], cam["source"], list(zone_map.polygons))

    if eyelevel and face_detector is not None:
        threads.append(threading.Thread(
            target=run_eyelevel_camera,
            args=(eyelevel["source"], face_detector, demographics_classifier, visit_tracker, conn),
            daemon=True,
        ))
    elif eyelevel is None and face_detector is not None:
        log.info("no eye-level camera configured - running face detection/demographics inline "
                 "on the overhead camera(s) instead")
    else:
        log.info("no eye-level camera configured (or --skip-demographics set) - counting/dwell only")

    if args.debug_video_stream:
        log.info("overhead camera video streaming enabled - powers the kiosk display and the "
                 "dashboard's /live page. Eye-level camera frames are never published "
                 "regardless of this flag (see run_eyelevel_camera).")

    log.info("starting ingestion: booth=%s overhead_cameras=%d", booth["booth_id"], len(overhead_cameras))
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
