"""Daily rollup scheduler. Per-frame zone/dwell/occupancy logic runs inline inside the ingestion
pipeline (see services/ingestion/pipeline.py) - this process only builds daily_summary rows once
a day has closed, so the API's /totals and reports don't have to recompute it on every request.
"""
import logging
import os
import time
from datetime import date, timedelta

import yaml

from services.metrics_engine import store
from services.metrics_engine.occupancy import build_daily_summary

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("metrics_engine")

CHECK_INTERVAL_S = 300


def main():
    booth_config = os.environ.get("BOOTH_CONFIG", "configs/booth.yaml")
    db_path = os.environ.get("DB_PATH", "data/events.db")
    with open(booth_config) as f:
        booth_id = yaml.safe_load(f)["booth_id"]

    conn = store.connect(db_path)
    log.info("metrics_engine rollup scheduler started: booth=%s", booth_id)

    last_rolled_up = None
    while True:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        if yesterday != last_rolled_up:
            summary = build_daily_summary(conn, booth_id, yesterday)
            log.info("rolled up daily_summary for %s: %s", yesterday, summary)
            last_rolled_up = yesterday
        time.sleep(CHECK_INTERVAL_S)


if __name__ == "__main__":
    main()
