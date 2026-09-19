"""Camera ingestion service. Phase 1: read frames from a video file/RTSP/USB source per booth.yaml."""
import logging
import time

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ingestion")

if __name__ == "__main__":
    log.info("ingestion service started (stub)")
    while True:
        time.sleep(60)
