"""Marketing kiosk display entrypoint. Runs full-screen on the booth's dedicated monitor,
showing live overhead-camera video with tracking boxes/trails plus aggregate stats. Reads from
the same local SQLite DB ingestion writes to (see data_source.py) - has no dependency on the
API service, and recovers automatically from a brief ingestion restart (stale/empty data just
ages out of the polled queries, see store.py's max_age_s cutoffs).

Requires DISPLAY (or Windows equivalent) and ingestion running with debug_video_stream enabled
(the default - see services/ingestion/main.py) for the overhead cameras this reads.
"""
import argparse
import logging
import os
import sys

from services.common.config import DEFAULT_BOOTH_CONFIG, DEFAULT_BOOTH_ID, DEFAULT_DB_PATH

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("kiosk_display")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--booth-config", default=os.environ.get("BOOTH_CONFIG", DEFAULT_BOOTH_CONFIG))
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", DEFAULT_DB_PATH))
    parser.add_argument("--booth-id", default=os.environ.get("BOOTH_ID", DEFAULT_BOOTH_ID))
    parser.add_argument("--poll-interval-ms", type=int,
                         default=int(float(os.environ.get("KIOSK_POLL_INTERVAL_S", "0.15")) * 1000))
    parser.add_argument("--fullscreen", action=argparse.BooleanOptionalAction,
                         default=os.environ.get("KIOSK_FULLSCREEN", "1") != "0")
    args = parser.parse_args()

    from PySide6.QtWidgets import QApplication

    from services.kiosk_display.data_source import KioskDataSource
    from services.kiosk_display.render.scene import KioskWindow

    data_source = KioskDataSource(args.db_path, args.booth_config, args.booth_id)

    app = QApplication(sys.argv)
    window = KioskWindow(data_source, poll_interval_ms=args.poll_interval_ms)
    if args.fullscreen:
        window.showFullScreen()
    else:
        window.resize(1600, 900)
        window.show()

    log.info("kiosk display started: booth=%s cameras=%s", args.booth_id,
              sorted(data_source.overhead_camera_ids))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
