"""Rule engine: capacity, no-coverage, traffic-spike. Phase 5: reads event store, pushes via webhook."""
import logging
import time

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("alerting")

if __name__ == "__main__":
    log.info("alerting service started (stub)")
    while True:
        time.sleep(60)
