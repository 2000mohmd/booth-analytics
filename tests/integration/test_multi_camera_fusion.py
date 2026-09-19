"""Multiple overhead cameras (needed when one camera's FOV can't cover a large booth) share
one VisitTracker. This checks the actual fusion - independent per-camera zone maps and track
namespaces still add up to one coherent occupancy/count picture - and that concurrent camera
threads hammering the same VisitTracker don't corrupt its state or crash.
"""
import threading

from services.metrics_engine.dwell import VisitTracker
from services.metrics_engine.zones import ZoneMap

ENTRANCE_ZONES = ZoneMap({"aisle": [[0, 0], [100, 0], [100, 20], [0, 20]],
                           "stand": [[0, 20], [100, 20], [100, 80], [0, 80]]})
BACK_ZONES = ZoneMap({"table": [[0, 0], [100, 0], [100, 60], [0, 60]]})


def test_two_cameras_fuse_into_one_occupancy_count():
    vt = VisitTracker(booth_id="booth-01", stopper_threshold_s=5.0)
    t0 = 1000.0

    vt.update("cam_entrance:1", "cam_entrance", ENTRANCE_ZONES.zone_for_point(50, 50), 50, 50, t0)
    vt.update("cam_back:1", "cam_back", BACK_ZONES.zone_for_point(50, 30), 50, 30, t0)

    assert vt.active_count() == 2  # one visitor in each camera's section, counted together


def test_concurrent_camera_threads_do_not_corrupt_shared_state():
    vt = VisitTracker(booth_id="booth-01", stopper_threshold_s=5.0)
    n_cameras, n_tracks_each, n_frames = 4, 10, 20
    errors = []

    def run_camera(cam_idx):
        cam_id = f"cam_{cam_idx}"
        try:
            for frame in range(n_frames):
                now = 1000.0 + frame
                for track_num in range(n_tracks_each):
                    vt.update(f"{cam_id}:{track_num}", cam_id, "stand", 50, 50, now)
                vt.expire_stale(now, grace_seconds=1000.0)  # never actually stale here - just exercises the lock
        except Exception as e:  # pragma: no cover - surfaced via `errors` below
            errors.append(e)

    threads = [threading.Thread(target=run_camera, args=(i,)) for i in range(n_cameras)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert vt.active_count() == n_cameras * n_tracks_each
