# Deployment

Two deployment targets are documented here: the original Linux edge-box runbook below, and a
**Windows** runbook (this project's actual target for the Saudi expo deployment - everything
runs on one Windows PC with an NVIDIA GPU, via Docker Desktop). Read the Windows section if
that's your case; the Linux section still applies as-is if you ever deploy to a dedicated Linux
edge box instead.

## Windows deployment (booth-analytics running on one PC)

1. Confirm Docker Desktop is installed with the WSL2 backend and GPU access working
   (`docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` should show
   your GPU). Set Docker Desktop to start on login (Settings → General).
2. Fill in `configs/booth.yaml` (copy from `booth.example.yaml`) with real camera sources -
   see the Linux section's step 2 below for the camera/zone details, identical on Windows.
3. Run `scripts/export_models.py` (and source the demographics models per its printed notes)
   so `models/` is populated before first boot.
4. `docker compose build && docker compose up -d` once manually to confirm it comes up clean -
   this brings up `ingestion` (GPU), `metrics_engine`, `api` (bound to `127.0.0.1:8000` only,
   not exposed on the venue LAN directly - see Access control below), and `dashboard` (nginx,
   port 8080).
5. Generate the ops dashboard's Basic Auth credentials (see Access control below) before
   relying on this for anything beyond local testing.
6. Register the auto-start/auto-restart tasks so the stack survives a reboot or crash:

   ```powershell
   # Daily reporting job (PDF/Excel export)
   .\deploy\windows\register-report-task.ps1

   # Marketing kiosk display app (separate from the Docker stack - see below)
   .\deploy\windows\register-kiosk-task.ps1
   ```

   Docker Desktop's own "start on login" setting (step 1) plus its default behavior of
   restarting previously-running containers handles the Compose stack itself; the two
   `register-*-task.ps1` scripts above cover the pieces that aren't part of that stack.
7. Reboot the PC and confirm the dashboard (`http://localhost:8080`) is reachable within a
   reasonable window, and that the kiosk display app comes up full-screen automatically - the
   Windows equivalent of the Linux runbook's Phase 8 reboot-recovery check.

### GPU inference

`configs/models.yaml` (the committed, real config) already has `execution_provider:
CUDAExecutionProvider`. `requirements.txt` pins `onnxruntime-gpu` to a version matched against
this repo's Dockerfile base image (`nvcr.io/nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04`) - see
that file's comment if you ever need to change either. `services/perception/detector.py`'s
`PersonDetector` verifies CUDA actually activated at startup and **raises** if it silently fell
back to CPU, rather than letting that happen invisibly - check `docker compose logs ingestion`
for the confirmation log line after bringing the stack up.

Use `configs/models.local.yaml` (CPU) instead only for local development without a GPU - never
point production `MODELS_CONFIG` at it.

### Access control

`services/dashboard/nginx.conf` gates everything except the public kiosk's own aggregate
endpoints behind HTTP Basic Auth. Generate credentials before deploying for real:

```powershell
.\deploy\windows\generate-htpasswd.ps1 -Username staff
```

This writes `deploy/secrets/htpasswd` (gitignored, mounted read-only into the `dashboard`
container). Restart the dashboard container after regenerating it:
`docker compose restart dashboard`.

The `api` service's port is bound to `127.0.0.1:8000` only (not the venue LAN) - the dashboard's
nginx is the only intended path in from the network. Basic Auth over plain HTTP sends
credentials base64-encoded, not encrypted; accept that risk for a short deployment or add TLS
termination at nginx if warranted.

### Public TV display (aggregate kiosk) vs. marketing kiosk app - two different things

- `http://localhost:8080/kiosk` is the original aggregate-only public display (large-format
  counters/charts, no video - see `services/dashboard/src/Kiosk.jsx`). Still works exactly as
  documented in the Linux section below if you want a second, simpler screen.
- **The marketing kiosk app** (`services/kiosk_display/`) is a separate, native PySide6
  application - not a browser page - showing live overhead-camera video with tracking boxes and
  motion trails, plus the same aggregate stats. It deliberately never shows the eye-level
  camera's feed (see `services/kiosk_display/data_source.py`'s module docstring). Requires
  `PySide6` installed (`pip install -r requirements-kiosk.txt`) and ingestion running with
  overhead-camera video streaming enabled (on by default - see
  `services/ingestion/main.py --debug-video-stream`).

  Run manually to test: `python -m services.kiosk_display.main`. For production, register the
  auto-start/auto-restart task (`deploy/windows/register-kiosk-task.ps1`) and configure Windows
  auto-login for the kiosk account plus `powercfg /change standby-timeout-ac 0` and
  `powercfg /change monitor-timeout-ac 0` so the screen never sleeps mid-event.

  **Booth signage**: since this app shows real camera video publicly, put up visible signage at
  the booth (e.g. "This area is monitored by AI cameras for a live technology demonstration")
  before doors open.

### Remote/cloud access (optional)

`services/cloud_sync` runs inside the Docker Compose stack (it's headless, like `alerting`) and
periodically POSTs aggregate-only numbers (occupancy, today's totals, demographics split,
hourly traffic, active alerts, daily summaries - see `services/cloud_sync/payload.py`'s
docstring for the exact, exhaustive list) to a remote endpoint, e.g. a Supabase REST endpoint or
any other HTTP-fronted store. Never sends raw video, per-track/bbox data, or individual visit
records. Set `CLOUD_SYNC_URL` (and `CLOUD_SYNC_API_KEY` if needed) in the environment before
`docker compose up`; the service idles harmlessly if unset. Local SQLite remains authoritative -
a down venue internet connection never affects the live event.

### Reporting

Same CLI as the Linux section below, scheduled via Task Scheduler instead of a systemd timer:

```powershell
.\deploy\windows\register-report-task.ps1
```

Registers a daily task (default 23:55) running the same `docker compose run --rm api python3
services/reporting/main.py ...` command documented below, with "run as soon as possible if a
scheduled start is missed" set so a day the PC was off still gets a report on next boot.

---

## Linux edge-box deployment

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
