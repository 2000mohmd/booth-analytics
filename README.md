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

- **Detector/tracker (`services/perception/detector.py`, `tracker.py`)** — verified
  end-to-end on a real laptop webcam (CPU, `yolov8n.onnx` exported via
  `scripts/export_models.py`): detection, ByteTrack tracking, zone/dwell and
  staff-marker filtering all produced real visit rows with plausible position
  traces. Not yet verified on GPU hardware or against multi-camera real footage -
  do that before trusting counts in a real deployment.
- **Demographics face detector (`services/perception/demographics.py`)** — verified
  end-to-end on a real laptop webcam: SCRFD (`models/scrfd.onnx`, via insightface's
  official distribution) detected a real face in 446/446 test frames, and the
  age-gender classifier (Intel OMZ's age-gender-recognition-retail-0013, run via
  the `openvino` runtime directly against its native IR export - there's no
  maintained IR->ONNX converter, so `DemographicsClassifier` supports both `.xml`
  and `.onnx` weights) gave a stable, consistent estimate across those frames.
  Decode math is also unit-tested (`tests/unit/test_face_detector_decode.py`).
  Weights are still not bundled/auto-downloaded (license/accuracy vetting stays a
  deliberate manual step - see `scripts/export_models.py`'s printed notes, which
  include the exact working fetch commands for both models). Not yet verified
  against multiple faces at once or the full multi-camera attribution path.
- **Cross-camera re-identification** is now handled for the common case - a visitor who walks
  from one overhead camera's section into an adjacent one, through a boundary declared in
  `zone_transitions` (see `configs/booth.example.yaml`), continues as one visit instead of two
  (`services/metrics_engine/dwell.py`, tested in `tests/integration/test_cross_camera_reid.py`).
  There's no appearance-based re-id model behind this - it's a time-window heuristic keyed on
  declared zone adjacency - so what's still unhandled: (1) a crossing through an *undeclared*
  boundary, or one that takes longer than that boundary's `max_gap_seconds`, still splits into
  two visits; (2) demographics attribution (`services/ingestion/pipeline.py`'s
  `attribute_demographics`) still only attaches a face to a visit when there's exactly one
  active stopper *booth-wide* and exactly one detected face at that moment - anything more is
  skipped rather than guessed, independent of whether the visit itself got re-identified. Both
  are documented v2 limitations, not bugs. All camera loops (however many overhead cameras + the
  one eye-level camera) run as threads in one process sharing a `VisitTracker`, which is
  genuinely multi-writer - it's lock-protected (`services/metrics_engine/dwell.py`) and the
  insert-stub/finalize ordering (a track's row is created the moment it appears, not just when
  it finalizes, so demographics attached mid-dwell don't get lost or wiped out later) is covered
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
