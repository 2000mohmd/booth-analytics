# Booth Visitor Analytics

Two-camera booth analytics pipeline: counting, dwell time, gender/age brackets,
heatmap, staff exclusion, alerts, dashboard, reporting. Runs on local edge
compute; raw video never leaves the ingestion process and is never written to
disk — only anonymous numeric events persist.

## Status: Phase 0 (scaffolding)

See the engineering build plan for the full phased roadmap and acceptance
criteria per phase.

## Dev setup

```bash
pip install -r requirements.txt
cp configs/booth.example.yaml configs/booth.yaml   # edit camera sources/zones
pytest
```

## Docker

```bash
docker-compose up
```

Requires the NVIDIA Container Toolkit for the `ingestion` service's GPU
reservation.
