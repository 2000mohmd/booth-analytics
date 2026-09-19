# Booth Visitor Analytics

Two-camera booth analytics pipeline: counting, dwell time, gender/age brackets,
heatmap, staff exclusion, alerts, dashboard, reporting. Runs on local edge
compute; raw video never leaves the ingestion process and is never written to
disk — only anonymous numeric events persist.

## Status

All services from the build plan are implemented (detection/tracking, zone/dwell
logic, staff exclusion, alerting, API, live dashboard, reporting, edge packaging).
What's still open, honestly:

- **Detector/tracker (`services/perception/detector.py`, `tracker.py`)** — real
  ultralytics/supervision wrappers, but never run end-to-end against real GPU
  hardware or real pedestrian footage from this environment. Verify on the dev
  GPU machine before trusting counts.
- **Demographics face detector (`services/perception/demographics.py`)** — the
  age/gender classifier is real and generic; `FaceDetector.detect_faces()`
  deliberately raises `NotImplementedError` because SCRFD's pre/post-processing
  depends on the exact ONNX export used, and no specific weights have been
  vetted yet (see `scripts/export_models.py`'s printed notes). Wire this up in
  Phase 3 once a model is chosen.
- **Cross-camera demographics attribution** — v1 does not do person re-identification
  across the two cameras. The overhead camera is the sole source of truth for
  counting/dwell/zones; the eye-level camera's demographics are attributed to
  the currently active stopper by time-window, not by spatial re-id. Fine for a
  single visitor at a time; ambiguous with multiple simultaneous stoppers - a
  known v1 limitation, not a bug.
- **PDF reports (`services/reporting/pdf.py`)** — WeasyPrint needs a system
  GTK/Pango install. That's present in the Docker image (via apt) but not on a
  bare Windows dev box - `services/reporting/data.py` (the actual number-crunching)
  is fully tested without it.
- **No real sample video** - `data/sample_videos/` is empty. Nothing here can
  fabricate real pedestrian footage; drop 2-3 real clips in before running
  Phase 1/2 acceptance tests, or record a short one from a webcam.
- **`docker-compose up` and the systemd unit** - written but not run in this
  environment (no Docker/GPU here). Validate on the actual dev/edge machine.

Everything else - zone/dwell math, staff-marker color detection, alert rules,
the SQLite event store, the FastAPI endpoints, the daily rollup, Excel export,
and the live dashboard - is implemented and covered by `pytest`, and the
dashboard has been visually verified end-to-end against a seeded database.

## Dev setup

```bash
pip install -r requirements.txt
cp configs/booth.example.yaml configs/booth.yaml   # edit camera sources/zones
pytest
```

## Run the API + dashboard locally (no camera needed)

```bash
DB_PATH=data/events.db BOOTH_ID=booth-01 uvicorn services.api.main:app --port 8000
cd services/dashboard && npm install && npm run dev
```

## Run ingestion against a real camera/video

```bash
python -m services.ingestion.main --booth-config configs/booth.yaml --debug-preview
```

Requires `models/` populated - run `python scripts/export_models.py` first, and
see its printed notes for the face/demographics models it can't auto-fetch.

## Docker (target deployment)

```bash
docker-compose up
```

Requires the NVIDIA Container Toolkit for the `ingestion` service's GPU
reservation. See `deploy/README.md` for edge install + systemd + power-loss notes.
