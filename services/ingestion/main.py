"""Camera ingestion entrypoint. Reads booth.yaml + models.yaml, runs the overhead camera's
detect/track/zone/dwell loop. Eye-level demographics loop lands in Phase 3.
"""
import argparse
import logging
import os

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
    args = parser.parse_args()

    booth = load_yaml(args.booth_config)
    models = load_yaml(args.models_config)

    overhead = next(c for c in booth["cameras"] if c["role"] == "overhead")

    detector = PersonDetector(
        weights_path=models["detector"]["weights"],
        confidence_threshold=models["detector"]["confidence_threshold"],
        device="cuda" if models.get("execution_provider") == "CUDAExecutionProvider" else "cpu",
    )
    tracker = PersonTracker()
    zone_map = ZoneMap(booth["zones"])
    visit_tracker = VisitTracker(
        booth_id=booth["booth_id"], zone_map=zone_map,
        stopper_threshold_s=booth["thresholds"]["dwell_seconds_stopper"],
    )
    conn = store.connect(args.db_path)

    log.info("starting overhead ingestion: booth=%s source=%s", booth["booth_id"], overhead["source"])

    from services.ingestion.pipeline import run_overhead_camera

    run_overhead_camera(
        source=overhead["source"], detector=detector, tracker=tracker,
        visit_tracker=visit_tracker, conn=conn, marker_config=booth["staff_marker"],
        debug_preview=args.debug_preview,
    )


if __name__ == "__main__":
    main()
