# Deployment Checklist - Saudi Arabia Expo Booth

This is the operational runbook for the actual event. It assumes everything in
`deploy/README.md`'s Windows section has already been set up once. Use this document on
event day and during the pre-event dry run.

## 1. Hardware

- [ ] Windows PC with NVIDIA GPU (confirmed available this session: RTX 3050 class or
      better recommended for 3 concurrent camera streams at full resolution).
- [ ] NVIDIA driver installed, supports CUDA 12.4 (`nvidia-smi` shows a driver version
      compatible with CUDA 12.4 - check before the event, not during).
- [ ] Docker Desktop installed, WSL2 backend, GPU passthrough working
      (`docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` shows the GPU).
- [ ] Sufficient disk space for Docker images + SQLite growth over the event's duration
      (the CUDA base image alone is ~2-3GB; budget headroom beyond that).
- [ ] UPS or equivalent power protection recommended - see Power-loss safety below.
- [ ] Dedicated monitor for the marketing kiosk display, separate from (or in addition to)
      whatever shows the ops dashboard.
- [ ] Stable network path from this PC to the NVR/cameras (wired preferred over Wi-Fi for
      the camera link if at all possible - RTSP is sensitive to jitter/loss).

## 2. Cameras

- [ ] Confirm exact camera count and roles for the real booth layout. This session's
      adopted design: a dedicated **entrance/event-traffic** camera + separate
      **kiosk-zone** camera(s) reporting independent counts (conversion rate =
      kiosk visitors / event visitors), rather than fusing everything into one number -
      see `services/metrics_engine/dwell.py`'s module docstring and
      `configs/booth.example.yaml`'s `zone_transitions` comments.
- [ ] Camera mounting height/angle: high-angle/overhead, not eye-level, for the
      entrance/kiosk cameras - both for detection accuracy (less occlusion in crowds) and
      because the marketing kiosk display shows this video live (see Privacy section -
      the "mostly heads/shoulders, not frontal faces" assumption depends on this).
- [ ] Eye-level demographics camera aimed at the busiest stop zone, positioned to catch
      frontal faces - this feed is NEVER shown on the marketing display (enforced in code,
      see `services/kiosk_display/data_source.py`).
- [ ] Run `python -m scripts.discover_cameras --host <nvr-ip>` (see script docstring) to
      confirm ONVIF discovery and pull exact RTSP URIs before hardcoding anything.
- [ ] Confirm RTSP stream choice: main stream (`subtype=0`, full resolution) once GPU
      inference is verified fast enough; sub-stream (`subtype=1`) only if still CPU-bound.
      This session found CPU-only detection couldn't keep pace with main-stream resolution.

## 3. Configuration

- [ ] `configs/booth.yaml` (gitignored, real per-venue config) has real camera IDs, roles,
      RTSP sources, and **calibrated zone polygons** - `scripts/calibrate_zones.py` must be
      run **on-site**, after cameras are physically mounted in their final position. The
      placeholder full-frame zones used during earlier testing are NOT valid for real
      stopper/passerby classification.
- [ ] `zone_transitions` in `booth.yaml` only declares physically-adjacent camera/zone
      pairs. Do NOT declare a transition between the entrance camera and the kiosk camera
      unless they are genuinely adjacent, physically overlapping sections - see
      `tests/integration/test_cross_camera_reid.py::test_handoff_through_unconfigured_zone_is_two_separate_visits`
      for what happens if you get this wrong (two separate, uncorrelated visits - which is
      the desired/correct behavior for non-adjacent zones).
- [ ] `configs/models.yaml` (committed) has `execution_provider: CUDAExecutionProvider` -
      confirm this is what's actually loaded in production (`MODELS_CONFIG` env var points
      at `/app/configs/models.yaml`, not `models.local.yaml`).
- [ ] RTSP URLs, camera credentials: pass as environment variables / in the gitignored
      `booth.yaml`, never hardcoded elsewhere or committed. Example env-var style if you
      prefer that over embedding credentials in the RTSP URL directly:
      ```
      NVR_HOST=192.168.1.50
      NVR_USER=admin
      NVR_PASSWORD=<real password, not admin123456>
      ```

## 4. Docker commands (reference)

```powershell
# Build everything
docker compose build

# Bring up the full stack
docker compose up -d

# Check status / logs
docker compose ps
docker compose logs -f ingestion
docker compose logs -f api

# Confirm GPU is active (look for the confirmation log line from
# services/perception/detector.py's _assert_cuda_compiled_in / _assert_cuda_session_active)
docker compose logs ingestion | Select-String "CUDAExecutionProvider"

# Restart a single service
docker compose restart ingestion

# Full stop
docker compose down
```

## 5. GPU requirements

- [ ] `requirements.txt`'s pinned `onnxruntime-gpu` version matches the Dockerfile's CUDA/
      cuDNN base image - see that file's comment. If either changes, re-verify the pairing
      via onnxruntime's release notes before deploying.
- [ ] `docker compose logs ingestion` shows the CUDA-active confirmation log line at
      startup, not a fallback warning. If it's missing or shows a CPU fallback, **do not
      proceed** - `services/perception/detector.py`'s `PersonDetector` is designed to raise
      loudly in this case; treat any RuntimeError here as a hard blocker, not something to
      work around.
- [ ] Re-run the per-camera detection cadence measurement (poll `live_cameras`/
      `live_tracks` timestamps and diff successive values - see this session's methodology)
      under full concurrent camera load before trusting real-time counts at the event.

## 6. Startup procedure

1. Power on the PC, let Windows auto-login (configured per `deploy/README.md`).
2. Confirm Docker Desktop started automatically and the compose stack is up
   (`docker compose ps` - all services should show `running`/`healthy`).
3. Confirm the kiosk display app launched full-screen automatically
   (Task Scheduler task `BoothAnalyticsKioskDisplay` - `Get-ScheduledTaskInfo`).
4. Open the ops dashboard (`http://localhost:8080`) and confirm login prompt appears and
   data loads after entering credentials.
5. Open the public kiosk view (`http://localhost:8080/kiosk`) and confirm it loads without
   a login prompt and shows live numbers.
6. Walk in front of each camera briefly and confirm the marketing kiosk display shows a
   tracking box.

## 7. Shutdown procedure

1. `docker compose down` (or leave running if the event continues overnight - the stack is
   designed to run unattended; only actually stop it if you need to, e.g. for maintenance).
2. If shutting down the PC: normal Windows shutdown is fine - SQLite WAL mode is designed
   to survive an unclean shutdown too (see Power-loss safety), but a clean shutdown is
   still preferable when there's a choice.

## 8. Recovery procedure

- **Ingestion container crashes/restarts**: `restart: unless-stopped` brings it back
  automatically. The kiosk display and dashboard both tolerate this gracefully (stale data
  ages out via the `max_age_s` cutoffs in `services/metrics_engine/store.py`, no crash).
- **A camera's RTSP stream drops**: `services/ingestion/pipeline.py`'s `_reconnect` retries
  with backoff automatically (up to `RECONNECT_MAX_ATTEMPTS`). If it exhausts retries and
  raises, the whole `ingestion` container restarts per its Docker restart policy.
- **Kiosk display app crashes**: Task Scheduler's restart policy relaunches it within
  seconds (`RestartCount`/`RestartInterval` - see `deploy/windows/register-kiosk-task.ps1`).
- **PC loses power and reboots**: auto-login + Docker Desktop "start on login" + the
  registered scheduled tasks should bring everything back without manual intervention -
  this is the reboot-recovery check that must be verified during the dry run, not assumed.
- **Internet goes down**: local system (ingestion, dashboard, API, kiosk display) is
  entirely unaffected - only `cloud_sync` (if enabled) silently queues/retries.

## 9. Backup procedure

- [ ] `data/events.db` (+ `-wal`/`-shm` files) is the entire system of record. Back it up
  periodically during the event (e.g. a scheduled copy to external storage) - there is no
  automatic off-box backup built into this project.
- [ ] Daily reports (PDF/Excel, via the scheduled reporting task) serve as a secondary,
  human-readable record - confirm the output directory is also backed up.

## 10. Privacy configuration

- [ ] Booth signage in place before doors open: real overhead-camera video with tracking
      boxes is shown on the marketing display - visitors should be informed (e.g. "This
      area is monitored by AI cameras for a live technology demonstration").
- [ ] Confirm the eye-level demographics camera's feed never appears on the kiosk display -
      enforced in code (`services/kiosk_display/data_source.py` refuses non-overhead camera
      IDs), but worth a manual spot-check during the dry run.
- [ ] Confirm no face images are ever written to disk or the database - demographics
      estimation (`services/perception/demographics.py`) operates on in-memory crops only;
      `services/metrics_engine/store.py`'s schema has no image/blob column on the `visits`
      table (only `live_debug_frames`, which is overhead-camera video for the kiosk
      display, ephemeral/overwritten, and explicitly not the eye-level camera - see that
      table's docstring).
- [ ] Confirm cloud sync (if enabled) only ever sends the aggregate payload shape - see
      `services/cloud_sync/payload.py`'s docstring for the exhaustive list of what's
      included, and its test file for the assertions that forbidden fields never appear.
- [ ] Age/gender are estimates, not identity - never presented to anyone as certain fact;
      `configs/models.yaml`'s `confidence_threshold` for the demographics model and
      `booth.yaml`'s `low_sample_size_demographics` threshold both exist specifically to
      flag low-confidence aggregates rather than reporting them as if certain.

## 11. Credentials

- [ ] Ops dashboard Basic Auth: generated via `deploy/windows/generate-htpasswd.ps1` -
      **the placeholder `staff`/`changeme123` used during development must be regenerated
      with a real password before the event.** Do this now if it hasn't been done.
- [ ] NVR/camera RTSP credentials: not the manufacturer default - confirm they were changed
      from any default password before deployment.
- [ ] Cloud sync API key (if used): stored as an environment variable
      (`CLOUD_SYNC_API_KEY`), never committed - confirm `.gitignore`/`deploy/secrets/`
      coverage before pushing any config changes to version control.
- [ ] `configs/booth.yaml` (contains RTSP credentials) is gitignored - confirmed by this
      project's `.gitignore`; double-check `git status` shows it untracked before any commit.

## 12. Known issues from verification testing (real, measured - not hypothetical)

Found via live testing against a real camera during this project's verification pass (not
simulated) - read before the event, not after something looks wrong on the day.

- **Counting accuracy depends on demographics/face-reacquire being active.** Tested with a
  single real person doing repeated walk-in/walk-out cycles:
  - **Without** demographics enabled (`--skip-demographics`, no face embeddings): 1 person's
    activity produced **8 separate visit records** and occupancy briefly showed **2
    concurrent people** when only 1 was ever present - a real, measured ~3-4x
    over-count from track fragmentation (ByteTrack losing and re-acquiring the same person
    under a new ID, with no face-based mechanism active to recognize it's the same person -
    see `services/metrics_engine/dwell.py`'s module docstring on same-camera duplicate
    tracks).
  - **With** demographics enabled (face embeddings active, matching this project's normal
    deployment shape - either an eye-level camera or per-camera face detection is always
    configured per `configs/booth.example.yaml`): the same kind of continuous single-person
    session produced **exactly 1 visit record**, stable occupancy throughout, correct
    dwell/stopper classification.
  - **Action**: never deploy with `--skip-demographics` (or without an eye-level camera) at
    the real event - the same-camera duplicate-track safety net requires it. Confirm the
    real deployment's `booth.yaml` has either an eye-level camera or per-overhead-camera face
    detection configured, not counting-only mode.
- **Age estimates have no real confidence score.** `services/perception/demographics.py`'s
  `DemographicsClassifier.estimate()` hardcodes `age_conf=1.0` for every prediction - the
  underlying model (age-gender-retail-0013) outputs a raw regression value, not a
  classification with genuine confidence. Gender *is* properly confidence-gated (falls back
  to `"unknown"` below threshold) - age is not. In testing, the same continuously-tracked
  person's `age_bracket` changed between two samples taken ~30 seconds apart (`18-35` then
  `36-55`) - a concrete illustration of why age estimates must be presented to the client as
  rough estimates, never as a precise, stable fact.

## 13. Event-day troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Dashboard shows stale/zero numbers | `ingestion` container down | `docker compose ps`, `docker compose logs ingestion`, `docker compose restart ingestion` |
| Kiosk display frozen/blank | App crashed, Task Scheduler hasn't restarted yet | Check `Get-ScheduledTaskInfo -TaskName BoothAnalyticsKioskDisplay`; manually relaunch if needed |
| "no signal" on one camera panel | RTSP stream dropped, reconnect in progress or exhausted | Check `docker compose logs ingestion` for reconnect warnings; power-cycle that camera if reconnect gave up |
| Detection looks very slow / laggy boxes | GPU fell back to CPU silently | Should be impossible per the loud CUDA check, but if seen: `docker compose logs ingestion` for the RuntimeError, restart the container |
| Dashboard login not accepted | Wrong credentials or htpasswd not regenerated | Re-run `generate-htpasswd.ps1`, `docker compose restart dashboard` |
| Counts look wrong (double-counting between entrance/kiosk) | An unintended `zone_transitions` entry was declared between non-adjacent cameras | Check `booth.yaml`'s `zone_transitions` - remove any entry connecting cameras that aren't physically adjacent |
| PC rebooted unexpectedly, nothing came back | Auto-login or Docker Desktop "start on login" not actually configured | Manually verify both OS-level settings - these are one-time manual setup steps, not automated by this project |
