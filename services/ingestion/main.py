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

import yaml

from services.metrics_engine import store
from services.metrics_engine.dwell import VisitTracker
from services.metrics_engine.zones import ZoneMap
from services.perception.detector import PersonDetector
from services.perception.tracker import PersonTracker

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ingestion")


def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--booth-config", default=os.environ.get("BOOTH_CONFIG", "configs/booth.yaml"))
    parser.add_argument("--models-config", default=os.environ.get("MODELS_CONFIG", "configs/models.yaml"))
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", "data/events.db"))
    parser.add_argument("--debug-preview", action="store_true")
    parser.add_argument("--skip-demographics", action="store_true",
                         help="run overhead-only (counting/dwell/zones) without the eye-level face pipeline")
    args = parser.parse_args()

    booth = load_yaml(args.booth_config)
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
    )

    from services.ingestion.pipeline import run_eyelevel_camera, run_overhead_camera

    threads = []
    for cam in overhead_cameras:
        zone_map = ZoneMap(cam.get("zones") or {})
        t = threading.Thread(
            target=run_overhead_camera,
            kwargs=dict(
                camera_id=cam["id"], source=cam["source"], detector=detector,
                tracker=PersonTracker(), zone_map=zone_map, visit_tracker=visit_tracker,
                conn=conn, marker_config=booth["staff_marker"], debug_preview=args.debug_preview,
            ),
            daemon=True,
        )
        threads.append(t)
        log.info("configured overhead camera: id=%s source=%s zones=%s",
                  cam["id"], cam["source"], list(zone_map.polygons))

    eyelevel = next((c for c in booth["cameras"] if c["role"] == "eyelevel"), None)
    if eyelevel and not args.skip_demographics:
        from services.perception.demographics import DemographicsClassifier, FaceDetector

        face_detector = FaceDetector(
            weights_path=models["face_detector"]["weights"],
            confidence_threshold=models["face_detector"]["confidence_threshold"],
        )
        demographics_classifier = DemographicsClassifier(
            weights_path=models["demographics"]["weights"],
            confidence_threshold=models["demographics"]["confidence_threshold"],
        )
        threads.append(threading.Thread(
            target=run_eyelevel_camera,
            args=(eyelevel["source"], face_detector, demographics_classifier, visit_tracker, conn),
            daemon=True,
        ))
    else:
        log.info("no eye-level camera configured (or --skip-demographics set) - counting/dwell only")

    log.info("starting ingestion: booth=%s overhead_cameras=%d", booth["booth_id"], len(overhead_cameras))
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
