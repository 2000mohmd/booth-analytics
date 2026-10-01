"""Periodic aggregate-only push to a cloud endpoint for remote viewing. Local SQLite
(data/events.db) stays the system of record - this is a one-way, best-effort sync layered on
top, never something the live event depends on. If the venue's internet is down, this silently
retries next tick and nothing about the local system is affected.

Posts JSON via plain urllib (no new dependency, same pattern as services/alerting/main.py's
webhook delivery) rather than a Postgres client library - this works directly against a
Supabase (or any other) REST endpoint without committing to a specific cloud provider's SDK.
Swap send_payload() for a real client if a direct DB connection is preferred later.
"""
import argparse
import json
import logging
import os
import time
import urllib.request

from services.cloud_sync.payload import build_sync_payload
from services.common.config import DEFAULT_BOOTH_ID, DEFAULT_DB_PATH
from services.metrics_engine import store

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cloud_sync")

POLL_SECONDS = 120.0  # "every few minutes" is plenty for someone checking in remotely - see
# services/cloud_sync/payload.py's docstring for what does (and never does) get sent


def send_payload(url: str, api_key: str | None, payload: dict) -> None:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"cloud sync endpoint returned HTTP {resp.status}")


def tick(conn, booth_id: str, url: str, api_key: str | None) -> None:
    payload = build_sync_payload(conn, booth_id)
    try:
        send_payload(url, api_key, payload)
        log.info("synced: occupancy=%s totals=%s", payload["occupancy"], payload["totals_today"])
    except Exception as e:  # best-effort - a down venue internet connection must never affect
        log.warning("cloud sync failed, will retry next tick: %s", e)  # the live event


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", DEFAULT_DB_PATH))
    parser.add_argument("--booth-id", default=os.environ.get("BOOTH_ID", DEFAULT_BOOTH_ID))
    parser.add_argument("--sync-url", default=os.environ.get("CLOUD_SYNC_URL"))
    parser.add_argument("--sync-api-key", default=os.environ.get("CLOUD_SYNC_API_KEY"))
    parser.add_argument("--poll-seconds", type=float,
                         default=float(os.environ.get("CLOUD_SYNC_POLL_SECONDS", POLL_SECONDS)))
    args = parser.parse_args()

    if not args.sync_url:
        # Idle rather than crash-loop: this service is optional (see docker-compose.yml's
        # comment on the cloud_sync entry) - a deployment that doesn't need remote access
        # shouldn't see this container endlessly restart in its logs.
        log.warning("CLOUD_SYNC_URL not set - cloud sync disabled, idling. Set it (or pass "
                    "--sync-url) to enable remote access to aggregate stats.")
        while True:
            time.sleep(3600)

    conn = store.connect(args.db_path)
    log.info("cloud sync started: booth=%s url=%s interval=%ss", args.booth_id, args.sync_url, args.poll_seconds)
    while True:
        tick(conn, args.booth_id, args.sync_url, args.sync_api_key)
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
