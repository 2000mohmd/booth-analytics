# Edge deployment

1. Copy the repo to `/opt/booth-analytics` on the edge box (Jetson or x86 mini-PC).
2. Fill in `configs/booth.yaml` (copy from `booth.example.yaml`) with real camera sources.
   The example ships with 3 overhead cameras (one camera's FOV can't cover this booth's
   floor) + 1 eye-level - adjust the camera list/zones to your actual layout. Run
   `scripts/calibrate_zones.py --camera-id <id> --source <source>` once per overhead camera
   to draw that camera's own zone polygons (pixel coordinates are camera-local).
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

## Public TV display (marketing screen)

`http://<edge-box-ip>:8080/kiosk` is a public-facing view - large-format live counters,
traffic chart, and gender split, cycling every 10s. It shows aggregate numbers only, never
raw video or anything that identifies a visitor, so it doesn't compromise the "zero video
retention" design even though it's on a public screen (see `services/dashboard/src/Kiosk.jsx`).

To drive an actual TV: cheapest option is any small stick/mini-PC on the venue network running
a Chromium-based browser in kiosk mode pointed at that URL, e.g.:

```bash
chromium --kiosk --noerrdialogs --disable-session-crashed-bubble http://<edge-box-ip>:8080/kiosk
```

Most commercial signage players and smart TVs' built-in browsers work too, as long as they can
reach the edge box's port 8080 on the venue Wi-Fi/LAN.

## Reporting

`reporting` is not a long-running container - it's a one-off CLI. Run it on demand or wire
it into a systemd timer / cron job on the host:

```bash
docker compose run --rm api python3 services/reporting/main.py --booth-id booth-01 --format pdf
docker compose run --rm api python3 services/reporting/main.py --booth-id booth-01 --format excel
```
