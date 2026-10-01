"""Rule engine loop: polls the event store every POLL_SECONDS, opens/resolves alerts,
delivers via webhook (stdlib urllib - no new dependency for a single POST).
"""
import argparse
import json
import logging
import os
import time
import urllib.request
import uuid
from datetime import datetime, timezone

from services.alerting.rules import capacity_exceeded, no_coverage, traffic_spike
from services.common.config import DEFAULT_BOOTH_CONFIG, DEFAULT_DB_PATH, load_yaml
from services.metrics_engine import store

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("alerting")

POLL_SECONDS = 5.0
SPIKE_WINDOW_SECONDS = 60.0


def send_webhook(url: str | None, payload: dict):
    if not url:
        log.info("ALERT (no webhook configured): %s", payload)
        return
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:  # webhook delivery is best-effort, never crash the alert loop over it
        log.warning("webhook delivery failed: %s", e)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _recent_stopper_count(conn, booth_id: str, window_seconds: float) -> int:
    cutoff = datetime.fromtimestamp(time.time() - window_seconds, tz=timezone.utc).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM visits WHERE booth_id=? AND is_stopper=1 AND entered_at >= ?",
        (booth_id, cutoff),
    ).fetchone()
    return row["n"]


def tick(conn, booth_id: str, thresholds: dict, webhook_url: str | None):
    latest = conn.execute(
        "SELECT * FROM occupancy_samples WHERE booth_id=? ORDER BY ts DESC LIMIT 1", (booth_id,)
    ).fetchone()
    if latest is None:
        return

    checks = {
        "capacity": capacity_exceeded(latest["current_count"], thresholds["capacity_max_occupancy"]),
        "no_coverage": no_coverage(latest["current_count"], latest["staff_count"]),
        "traffic_spike": traffic_spike(
            _recent_stopper_count(conn, booth_id, SPIKE_WINDOW_SECONDS),
            thresholds["traffic_spike_per_minute"],
        ),
    }

    active = {r["type"]: r["alert_id"] for r in store.active_alerts(conn, booth_id)}

    for alert_type, is_active in checks.items():
        if is_active and alert_type not in active:
            alert_id = str(uuid.uuid4())
            detail = json.dumps(dict(latest))
            store.open_alert(conn, alert_id, booth_id, _now_iso(), alert_type, detail)
            send_webhook(webhook_url, {"alert_id": alert_id, "type": alert_type, "detail": detail})
        elif not is_active and alert_type in active:
            store.resolve_alert(conn, active[alert_type], _now_iso())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--booth-config", default=os.environ.get("BOOTH_CONFIG", DEFAULT_BOOTH_CONFIG))
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", DEFAULT_DB_PATH))
    parser.add_argument("--webhook-url", default=os.environ.get("ALERT_WEBHOOK_URL"))
    args = parser.parse_args()

    booth = load_yaml(args.booth_config)

    conn = store.connect(args.db_path)

    log.info("alerting service started: booth=%s", booth["booth_id"])
    while True:
        tick(conn, booth["booth_id"], booth["thresholds"], args.webhook_url)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
