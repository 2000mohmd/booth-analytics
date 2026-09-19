# Edge deployment

1. Copy the repo to `/opt/booth-analytics` on the edge box (Jetson or x86 mini-PC).
2. Fill in `configs/booth.yaml` (copy from `booth.example.yaml`) with real camera sources
   and run `scripts/calibrate_zones.py` to draw the zone polygons.
3. Run `scripts/export_models.py` (and source the demographics models per its printed notes)
   so `models/` is populated before first boot.
4. `docker compose build && docker compose up -d` once manually to confirm it comes up clean.
5. Install the systemd unit so it survives a reboot / crash:

   ```bash
   sudo cp deploy/booth-analytics.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now booth-analytics
   ```

6. Reboot the box and confirm the dashboard (port 8080) is reachable within 60s - this is
   the Phase 8 acceptance test. `journalctl -u booth-analytics` for boot-time logs.

## Power-loss safety

SQLite WAL mode (already on, see `services/metrics_engine/store.py`) means a hard power
cut loses at most the last uncommitted write, not the whole file. Verify this holds on the
actual target hardware by pulling power mid-write during a test run before trusting it at
a live event - WAL correctness assumptions can differ across filesystems/storage media.

## Reporting

`reporting` is not a long-running container - it's a one-off CLI. Run it on demand or wire
it into a systemd timer / cron job on the host:

```bash
docker compose run --rm api python3 services/reporting/main.py --booth-id booth-01 --format pdf
docker compose run --rm api python3 services/reporting/main.py --booth-id booth-01 --format excel
```
