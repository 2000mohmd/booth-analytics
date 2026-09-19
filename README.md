# Booth Visitor Analytics

Multi-camera booth analytics pipeline: counting, dwell time, gender/age brackets,
heatmap, staff exclusion, alerts, dashboard, reporting. Runs on local edge
compute; raw video never leaves the ingestion process and is never written to
disk — only anonymous numeric events persist.

The example config ships with **3 overhead cameras + 1 eye-level camera**: one overhead
camera's field of view can't cover a large booth's floor, so each overhead camera owns a
section (its own zone polygons, in its own pixel coordinates) and all of them fuse into one
shared counting/dwell ledger (`services/metrics_engine/dwell.py`'s `VisitTracker`, shared
across camera threads in one ingestion process). One eye-level camera is enough for
demographics, since a stopper already dwells for several seconds in one spot.

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
- **No cross-camera re-identification, anywhere.** This shows up two ways: (1) a visitor
  who physically walks from one overhead camera's section into another's is counted as two
  separate visits, not one continuous one - fine when sections are non-overlapping and
  visitors don't cross between them mid-visit, wrong if they do; (2) demographics attribution
  (`services/ingestion/pipeline.py`'s `attribute_demographics`) only attaches a face to a
  visit when there's exactly one active stopper *booth-wide* and exactly one detected face at
  that moment - anything more is skipped rather than guessed. Both are documented v1
  limitations, not bugs. All camera loops (however many overhead cameras + the one eye-level
  camera) run as threads in one process sharing a `VisitTracker`, which is now genuinely
  multi-writer - it's lock-protected (`services/metrics_engine/dwell.py`) and the insert-stub/
  finalize ordering (a track's row is created the moment it appears, not just when it
  finalizes, so demographics attached mid-dwell don't get lost or wiped out later) is covered
  by `tests/integration/test_visit_lifecycle.py` and `test_multi_camera_fusion.py`.
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

For CI or a machine without a GPU, `requirements-test.txt` is a lighter subset that skips
`onnxruntime-gpu`/`ultralytics`/`supervision`/`weasyprint` - none of those are touched by the
test suite (they're lazily imported only inside the model wrapper classes). `.github/workflows/test.yml`
runs `ruff check` + `pytest` on every push, plus a dashboard build check.

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
