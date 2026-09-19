"""Zone logic, dwell calc, occupancy, heatmap accumulation. Phase 2: consumes tracks, writes to SQLite event store."""
import logging
import time

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("metrics_engine")

if __name__ == "__main__":
    log.info("metrics_engine service started (stub)")
    while True:
        time.sleep(60)
