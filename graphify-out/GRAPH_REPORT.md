# Graph Report - booth-analytics  (2026-09-29)

## Corpus Check
- 33 files · ~27,881 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 636 nodes · 1129 edges · 49 communities (26 shown, 23 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 29 edges (avg confidence: 0.86)
- Token cost: 82,873 input · 0 output

## Community Hubs (Navigation)
- Cross-Camera Fusion & Dedup
- Cloud Sync & Storage
- Demographics Estimation
- Demographics Privacy & Config
- Overhead Camera Pipeline
- Kiosk Motion Trail Effects
- GPU/Windows Production Deployment
- Reporting Service
- CUDA Person Detector
- REST/WebSocket API
- Zone Polygon Testing
- Model & Camera Discovery Config
- Zone Calibration Tool
- Alerting Rule Engine
- Dashboard Build Tooling
- Accuracy Benchmarking
- Live Debug Track View
- Ops Dashboard UI
- Public Kiosk TV UI
- Dashboard Dev Dependencies
- Dashboard Branding Assets
- Dashboard Lint Config
- README Architecture Concepts
- npm Scripts
- Dashboard Runtime Dependencies
- CI Test Pipeline
- Multi-Camera Booth Config
- Staff Marker Config
- Alert Thresholds Config
- Local CUDA Provider Config
- Local Face Detector Config
- Local Face Recognition Config
- Linux Edge Runbook
- Backup Procedure
- Event-Day Troubleshooting
- PDF Reporting Limitation
- NumPy Reference

## God Nodes (most connected - your core abstractions)
1. `VisitTracker` - 34 edges
2. `KioskDataSource` - 20 edges
3. `connect()` - 20 edges
4. `TrailTracker` - 17 edges
5. `PersonDetector` - 17 edges
6. `tick()` - 14 edges
7. `run_overhead_camera()` - 14 edges
8. `insert_visit()` - 13 edges
9. `ZoneMap` - 12 edges
10. `_tracker()` - 12 edges

## Surprising Connections (you probably didn't know these)
- `Public TV display (aggregate kiosk)` --semantically_similar_to--> `Privacy configuration checklist`  [INFERRED] [semantically similar]
  deploy/README.md → DEPLOYMENT_CHECKLIST.md
- `Vite framework logo (default scaffold asset)` --references--> `Booth Analytics dashboard (React+Vite+Tailwind+Recharts)`  [AMBIGUOUS]
  services/dashboard/src/assets/vite.svg → services/dashboard/README.md
- `DemographicsClassifier (referenced in README)` --shares_data_with--> `Demographics model config (age_gender_retail_0013)`  [INFERRED]
  README.md → configs/models.yaml
- `Hardware requirements checklist` --conceptually_related_to--> `ingestion service (GPU)`  [INFERRED]
  DEPLOYMENT_CHECKLIST.md → docker-compose.yml
- `Age estimate has no real confidence score` --conceptually_related_to--> `Demographics model config (age_gender_retail_0013)`  [INFERRED]
  DEPLOYMENT_CHECKLIST.md → configs/models.yaml

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **CI test workflow (pytest + ruff + dashboard build)** — github_workflows_test_pytest_job, github_workflows_test_dashboard_build_job, github_workflows_test_ruff_check [EXTRACTED 1.00]
- **Dashboard brand/visual identity assets (favicon, hero, icon sprite)** — services_dashboard_public_favicon_faviconimage, services_dashboard_src_assets_hero_heroimage, services_dashboard_public_icons_iconsimage [INFERRED 0.75]
- **Loud CUDA-failure verification pattern** — services_perception_detector, configs_models_execution_provider, requirements_onnxruntime_gpu_pin, deployment_checklist_gpu_verification [INFERRED 0.85]
- **Face-embedding-based same-camera track dedup** — configs_models_face_recognition, services_metrics_engine_dwell, deployment_checklist_demographics_dedup_finding [INFERRED 0.80]
- **Ops dashboard access control chain** — docker_compose_api_service, deploy_windows_generate_htpasswd, deploy_readme_access_control [INFERRED 0.80]

## Communities (49 total, 23 thin omitted)

### Community 0 - "Cross-Camera Fusion & Dedup"
Cohesion: 0.05
Nodes (45): Face recognition model config (w600k_mbf, optional dedup), Entrance vs kiosk-zone camera layout, Demographics-off track fragmentation finding, Zone transitions adjacency rule, _iso(), Per-track zone/dwell bookkeeping. One VisitTracker per booth, shared across…, A brand-new track just appeared at (camera_id, zone), maybe with a face…, A brand-new track just appeared with a face embedding - check whether it's… (+37 more)

### Community 1 - "Cloud Sync & Storage"
Cohesion: 0.06
Nodes (47): Connection, contextlib, Power-loss safety (SQLite WAL mode), json, pytest, main(), Periodic aggregate-only push to a cloud endpoint for remote viewing. Local…, send_payload() (+39 more)

### Community 2 - "Demographics Estimation"
Cohesion: 0.07
Nodes (33): numpy, _age_to_bracket(), decode_scrfd_outputs(), DemographicEstimate, DemographicsClassifier, _distance2bbox(), FaceDetector, _nms() (+25 more)

### Community 3 - "Demographics Privacy & Config"
Cohesion: 0.06
Nodes (38): Demographics model config (age_gender_retail_0013), demographics model config (local override), Public TV display (aggregate kiosk), Age estimate has no real confidence score, Privacy configuration checklist, logging, Path, pyside6_qtcore (+30 more)

### Community 4 - "Overhead Camera Pipeline"
Cohesion: 0.07
Nodes (33): cv2, Event, PersonTracker, attribute_demographics(), _draw_tracks(), LatestFrameReader, _publish_debug_video(), Per-camera frame loop: detect -> track -> staff-filter -> zone/dwell update ->… (+25 more)

### Community 5 - "Kiosk Motion Trail Effects"
Cohesion: 0.08
Nodes (23): QLabel, QPainter, QVBoxLayout, QWidget, Client-side motion trails and appearance pulses, computed from successive…, One instance per camera_id (or share across cameras by namespacing track_id…, [(x, y, alpha)] oldest-to-newest, alpha fading from 0 to 1., 0 if not a recently-appeared track, fading 1 -> 0 over PULSE_DURATION_S if it… (+15 more)

### Community 6 - "GPU/Windows Production Deployment"
Cohesion: 0.08
Nodes (28): execution_provider: CUDAExecutionProvider (loud-fail design), dataclasses, Ops dashboard access control (Basic Auth + localhost API), GPU inference setup (Windows), Marketing kiosk app (native PySide6, video display), Remote/cloud access (cloud_sync), Windows deployment runbook, Credentials management checklist (+20 more)

### Community 7 - "Reporting Service"
Cohesion: 0.11
Nodes (24): datetime, Scheduled reporting (PDF/Excel), openpyxl, services_metrics_engine, main(), Daily rollup scheduler. Per-frame zone/dwell/occupancy logic runs inline inside…, build_daily_summary(), Periodic occupancy sampling and end-of-day aggregation into daily_summary. (+16 more)

### Community 8 - "CUDA Person Detector"
Cohesion: 0.10
Nodes (19): ndarray, PersonDetector, One instance can safely be shared across several overhead camera threads…, First-line check: does this onnxruntime-gpu install even have the CUDA provider…, ultralytics' ONNX backend does not raise if CUDAExecutionProvider fails to…, _FakePredictor, _FakeSession, _FakeYOLO (+11 more)

### Community 9 - "REST/WebSocket API"
Cohesion: 0.12
Nodes (25): asyncio, fastapi, get, Row, alerts_active(), debug_video_frame(), demographics_today(), dwell_distribution() (+17 more)

### Community 10 - "Zone Polygon Testing"
Cohesion: 0.15
Nodes (21): Polygon-in/out zone tests. Zone order in config (aisle -> stand -> table)…, ZoneMap, shapely_geometry, Regression test for the ordering bug: demographics get attached to a track…, Two different cameras' ByteTrack streams both number their first track '1' -…, test_active_and_staff_counts(), test_active_stopper_visit_ids_excludes_staff_and_aisle(), test_active_stopper_visit_ids_reflects_live_dwell() (+13 more)

### Community 11 - "Model & Camera Discovery Config"
Cohesion: 0.11
Nodes (20): argparse, Person detector model config (yolov8n), Face detector model config (scrfd), detector model config (local override), onvif, os, QMainWindow, _default_wsdl_dir() (+12 more)

### Community 12 - "Zone Calibration Tool"
Cohesion: 0.13
Nodes (18): pathlib, _find_camera(), _grab_first_frame(), Interactive tool: click points to draw zone polygons on a paused frame from a…, run(), _save(), load_yaml(), main() (+10 more)

### Community 13 - "Alerting Rule Engine"
Cohesion: 0.21
Nodes (16): main(), _now_iso(), Rule engine loop: polls the event store every POLL_SECONDS, opens/resolves…, _recent_stopper_count(), send_webhook(), tick(), capacity_exceeded(), no_coverage() (+8 more)

### Community 14 - "Dashboard Build Tooling"
Cohesion: 0.18
Nodes (11): oxlint, tailwindcss, @tailwindcss/vite, @types/react, @types/react-dom, vite, @vitejs/plugin-react, name (+3 more)

### Community 15 - "Accuracy Benchmarking"
Cohesion: 0.27
Nodes (9): csv, compare(), load_ground_truth(), main(), Compare system counts (from the event store) against a manually-recorded…, conn(), fixture, test_compare_computes_diffs() (+1 more)

### Community 16 - "Live Debug Track View"
Cohesion: 0.29
Nodes (5): react, LiveTrack(), ZONE_COLORS, fetchJSON(), useLiveTracks()

### Community 17 - "Ops Dashboard UI"
Cohesion: 0.24
Nodes (5): react-dom, App(), bucketDwell(), COLORS, services_dashboard_src_index

### Community 18 - "Public Kiosk TV UI"
Cohesion: 0.29
Nodes (4): recharts, COLORS, Kiosk(), useLiveData()

### Community 19 - "Dashboard Dev Dependencies"
Cohesion: 0.25
Nodes (8): devDependencies, oxlint, tailwindcss, @tailwindcss/vite, @types/react, @types/react-dom, vite, @vitejs/plugin-react

### Community 20 - "Dashboard Branding Assets"
Cohesion: 0.29
Nodes (7): dashboard-build CI Job, dashboard index.html entry point, Favicon: purple 3D isometric cube/tile icon, Icon sprite sheet: social/doc icons (Bluesky, Discord, GitHub, X, docs, social), Booth Analytics dashboard (React+Vite+Tailwind+Recharts), Hero image: purple 3D isometric cube illustration, Vite framework logo (default scaffold asset)

### Community 21 - "Dashboard Lint Config"
Cohesion: 0.33
Nodes (5): plugins, rules, react/only-export-components, react/rules-of-hooks, $schema

### Community 22 - "README Architecture Concepts"
Cohesion: 0.40
Nodes (5): zone_transitions config (camera boundary re-id), attribute_demographics (referenced in README), Booth Visitor Analytics (project), Cross-camera re-identification (time-window heuristic), VisitTracker (referenced in README)

### Community 23 - "npm Scripts"
Cohesion: 0.40
Nodes (5): scripts, build, dev, lint, preview

### Community 24 - "Dashboard Runtime Dependencies"
Cohesion: 0.50
Nodes (4): dependencies, react, react-dom, recharts

### Community 25 - "CI Test Pipeline"
Cohesion: 0.67
Nodes (3): pytest CI Job, ruff check step, requirements-test.txt (CI/light test subset)

## Ambiguous Edges - Review These
- `Booth Analytics dashboard (React+Vite+Tailwind+Recharts)` → `Vite framework logo (default scaffold asset)`  [AMBIGUOUS]
  services/dashboard/src/assets/vite.svg · relation: references

## Knowledge Gaps
- **50 isolated node(s):** `plugins`, `react/only-export-components`, `react/rules-of-hooks`, `$schema`, `react` (+45 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 228 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **23 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Booth Analytics dashboard (React+Vite+Tailwind+Recharts)` and `Vite framework logo (default scaffold asset)`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **Why does `Privacy configuration checklist` connect `Demographics Privacy & Config` to `Cloud Sync & Storage`, `Demographics Estimation`?**
  _High betweenness centrality (0.195) - this node is a cross-community bridge._
- **Why does `Public TV display (aggregate kiosk)` connect `Demographics Privacy & Config` to `Public Kiosk TV UI`?**
  _High betweenness centrality (0.154) - this node is a cross-community bridge._
- **Why does `VisitTracker` connect `Cross-Camera Fusion & Dedup` to `Cloud Sync & Storage`, `Zone Polygon Testing`?**
  _High betweenness centrality (0.107) - this node is a cross-community bridge._
- **What connects `plugins`, `react/only-export-components`, `react/rules-of-hooks` to the rest of the system?**
  _50 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Cross-Camera Fusion & Dedup` be split into smaller, more focused modules?**
  _Cohesion score 0.050203527815468114 - nodes in this community are weakly interconnected._
- **Should `Cloud Sync & Storage` be split into smaller, more focused modules?**
  _Cohesion score 0.06140350877192982 - nodes in this community are weakly interconnected._