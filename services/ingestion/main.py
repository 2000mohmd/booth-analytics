"""Camera ingestion entrypoint. Reads booth.yaml + models.yaml, runs the overhead camera's
detect/track/zone/dwell loop and the eye-level camera's demographics loop as two threads in
one process - they share one VisitTracker in memory, which is how the eye-level loop knows
which track is an active stopper right now (see dwell.VisitTracker.active_stopper_visit_ids).
A DB is the only channel between separate processes/containers, and that state changes every
frame, so this stays one process per booth rather than one container per camera.
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

    overhead = next(c for c in booth["cameras"] if c["role"] == "overhead")

    detector = PersonDetector(
        weights_path=models["detector"]["weights"],
        confidence_threshold=models["detector"]["confidence_threshold"], device=device,
    )
    tracker = PersonTracker()
    zone_map = ZoneMap(booth["zones"])
    conn = store.connect(args.db_path)
    visit_tracker = VisitTracker(
        booth_id=booth["booth_id"], zone_map=zone_map,
        stopper_threshold_s=booth["thresholds"]["dwell_seconds_stopper"],
        on_track_created=lambda stub: store.insert_visit(conn, stub),
    )

    from services.ingestion.pipeline import run_eyelevel_camera, run_overhead_camera

    threads = []
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
        t = threading.Thread(
            target=run_eyelevel_camera,
            args=(eyelevel["source"], face_detector, demographics_classifier, visit_tracker, conn),
            daemon=True,
        )
        threads.append(t)
    else:
        log.info("no eye-level camera configured (or --skip-demographics set) - counting/dwell only")

    log.info("starting overhead ingestion: booth=%s source=%s", booth["booth_id"], overhead["source"])
    for t in threads:
        t.start()

    run_overhead_camera(
        source=overhead["source"], detector=detector, tracker=tracker,
        visit_tracker=visit_tracker, conn=conn, marker_config=booth["staff_marker"],
        debug_preview=args.debug_preview,
    )


if __name__ == "__main__":
    main()
